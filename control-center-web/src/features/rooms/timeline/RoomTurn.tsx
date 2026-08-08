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
import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';

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
import type {
  PrivateSessionProjection,
  RoomKernelProjection,
} from '@/contracts/room-kernel-reducer';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import { publicAgentErrorText } from '@/features/agent/public-error';
import { AgentBlocks, MarkdownBody } from '@/features/agent/timeline/BlockRenderer';
import {
  PublicToolError,
  PublicToolFields,
  PublicToolOutput,
  PublicToolRequest,
  SemanticToolPreview,
  ToolRunningPreview,
} from '@/features/agent/timeline/ActivitySummary';
import {
  toggleDisclosureOnKeyPreservingAnchor,
  toggleDisclosurePreservingAnchor,
} from '@/features/agent/timeline/disclosure-anchor';
import {
  publicToolResultView,
  type PublicToolResultView,
} from '@/features/agent/timeline/public-tool-result';
import { hasToolArtifacts, ToolArtifactOutput } from '@/features/agent/timeline/ToolArtifactOutput';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { canonicalToolId, publicToolName } from '@/features/agent/tool-presentation';
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
import {
  RoomTaskDeliveryDetails,
  roomTaskTodoSummary,
  RoomTaskTodoDetails,
} from '../kernel/RoomTaskAuthorityDetails';
import { RoomTaskUpdatedAt, useRoomTaskUpdateClock } from '../kernel/RoomTaskUpdatedAt';
import type {
  PendingRoomQuestion,
  RoomQuestionAnswerKind,
} from '../room-question';
import { RoomQuestionDialog } from '../RoomQuestionDialog';
import {
  roomProjection,
  useRoomLiveStore,
  type RoomKernelSyncProjection,
} from '../state/live-store';
import {
  RoomStartActionGate,
  roomRootExecutionPlan,
  roomRootRequiresStartAction,
} from './RoomStartActionGate';
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
  kernelRootsById?: RoomKernelProjection['rootsById'];
  kernelDispatchesById?: RoomKernelProjection['dispatchesById'];
  kernelTasksById?: RoomKernelProjection['tasksById'];
  kernelTaskUpdatedAtMsById?: RoomKernelProjection['taskUpdatedAtMsById'];
  kernelSessionsById?: RoomKernelProjection['sessionsById'];
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
    answerKind: RoomQuestionAnswerKind,
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

type RoomTurnChronologicalItem =
  | { kind: 'message'; key: string; message: RoomMessageProjection }
  | {
      kind: 'lane';
      key: string;
      lane: RoomExecutionLane;
      activities: RoomActivityProjection[];
      continuation: boolean;
      includePersistentDetails: boolean;
    };

type RoomTurnChronologicalAtom =
  | { kind: 'message'; message: RoomMessageProjection; sourceIndex: number }
  | {
      kind: 'lane_message';
      message: RoomMessageProjection;
      lane: RoomExecutionLane;
      sourceIndex: number;
    }
  | {
      kind: 'activity';
      activity: RoomActivityProjection;
      lane: RoomExecutionLane;
      sourceIndex: number;
    };

function roomTurnChronologicalStream(
  lanes: RoomExecutionLane[],
  messages: RoomMessageProjection[],
): RoomTurnChronologicalItem[] {
  if (!lanes.length) {
    return messages.map((message) => ({
      kind: 'message',
      key: `message:${message.id}`,
      message,
    }));
  }
  const cardMessageIds = new Set(
    messages.filter(roomMessageBelongsInExecutionCard).map((message) => message.id),
  );
  const laneMessageIds = new Set(
    lanes.flatMap((lane) => lane.messageIds.filter((id) => cardMessageIds.has(id))),
  );
  const atoms: RoomTurnChronologicalAtom[] = messages
    .filter((message) => !laneMessageIds.has(message.id))
    .map((message, sourceIndex) => ({
      kind: 'message',
      message,
      sourceIndex,
    }));
  let activityIndex = 0;
  for (const lane of lanes) {
    const firstLaneMessage = lane.messageIds
      .map((messageId) => messages.find((message) => message.id === messageId))
      .filter((message): message is RoomMessageProjection => Boolean(message))
      .sort((left, right) => (
        (left.chronology?.roomEventSequence ?? left.sequence ?? Number.MAX_SAFE_INTEGER)
        - (right.chronology?.roomEventSequence ?? right.sequence ?? Number.MAX_SAFE_INTEGER)
        || left.createdAtMs - right.createdAtMs
      ))[0];
    if (firstLaneMessage) {
      atoms.push({
        kind: 'lane_message',
        message: firstLaneMessage,
        lane,
        sourceIndex: activityIndex,
      });
      activityIndex += 1;
    }
    for (const activity of lane.activities) {
      atoms.push({ kind: 'activity', activity, lane, sourceIndex: activityIndex });
      activityIndex += 1;
    }
  }
  atoms.sort(compareRoomTurnChronologicalAtoms);

  const result: RoomTurnChronologicalItem[] = [];
  const renderedLaneKeys = new Set<string>();
  for (const atom of atoms) {
    if (atom.kind === 'message') {
      result.push({
        kind: 'message',
        key: `message:${atom.message.id}`,
        message: atom.message,
      });
      continue;
    }
    if (renderedLaneKeys.has(atom.lane.key)) continue;
    renderedLaneKeys.add(atom.lane.key);
    result.push({
      kind: 'lane',
      key: `${atom.lane.key}:work`,
      lane: atom.lane,
      activities: atom.lane.activities,
      continuation: false,
      includePersistentDetails: true,
    });
  }
  for (const lane of lanes) {
    if (renderedLaneKeys.has(lane.key)) continue;
    renderedLaneKeys.add(lane.key);
    result.push({
      kind: 'lane',
      key: `${lane.key}:segment:empty`,
      lane,
      activities: [],
      continuation: false,
      includePersistentDetails: true,
    });
  }
  return result;
}

function roomMessageBelongsInExecutionCard(message: RoomMessageProjection): boolean {
  return message.role !== 'user' || Boolean(message.answerToPostId);
}

function compareRoomTurnChronologicalAtoms(
  left: RoomTurnChronologicalAtom,
  right: RoomTurnChronologicalAtom,
): number {
  const leftSequence = left.kind === 'activity'
    ? left.activity.sequence
    : left.message.chronology?.roomEventSequence ?? left.message.sequence;
  const rightSequence = right.kind === 'activity'
    ? right.activity.sequence
    : right.message.chronology?.roomEventSequence ?? right.message.sequence;
  if (leftSequence !== undefined && rightSequence !== undefined && leftSequence !== rightSequence) {
    return leftSequence - rightSequence;
  }
  const leftAtMs = left.kind === 'activity' ? left.activity.createdAtMs : left.message.createdAtMs;
  const rightAtMs = right.kind === 'activity' ? right.activity.createdAtMs : right.message.createdAtMs;
  if (leftAtMs !== rightAtMs) return leftAtMs - rightAtMs;
  if (leftSequence !== undefined || rightSequence !== undefined) {
    if (leftSequence === undefined) return 1;
    if (rightSequence === undefined) return -1;
  }
  if (left.kind !== right.kind) {
    const rank: Record<RoomTurnChronologicalAtom['kind'], number> = {
      message: 0,
      lane_message: 1,
      activity: 2,
    };
    return rank[left.kind] - rank[right.kind];
  }
  if (left.sourceIndex !== right.sourceIndex) return left.sourceIndex - right.sourceIndex;
  const leftId = left.kind === 'activity' ? left.activity.id : left.message.id;
  const rightId = right.kind === 'activity' ? right.activity.id : right.message.id;
  return leftId.localeCompare(rightId);
}

const roomActiveEventFreshnessMs = 60_000;

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
  kernelSessionsById,
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
    Object.fromEntries(Object.values(kernelDispatchesById ?? {}).map((dispatch) => (
      [dispatch.dispatchId, dispatch.taskId]
    ))),
  );
  const latestTaskLaneKeyByTaskId = roomLatestTaskLaneKeys(
    lanes,
    projection,
    kernelDispatchesById,
  );
  const responseUsageActivities = turn.activityIds
    .map((activityId) => projection.activitiesById[activityId])
    .filter((activity): activity is RoomActivityProjection => Boolean(activity));
  const rootId = turn.rootId || turnId;
  const kernelRoot = kernelRootsById?.[rootId];
  const kernelRootState = kernelRoot?.state;
  const kernelRootFailed = kernelRootState === 'failed';
  const kernelRootAborted = ['cancelled', 'cancelled_with_unknowns'].includes(
    kernelRootState ?? '',
  );
  const rootTerminal = (
    ['completed', 'failed', 'aborted'].includes(turn.status)
    || ['completed', 'failed', 'cancelled', 'cancelled_with_unknowns'].includes(
      kernelRootState ?? '',
    )
  );
  const pendingAction = rootTerminal
    ? undefined
    : pendingRoomSessionAction(activities, projection, lanes, room);
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
  const requiresStartAction = roomRootRequiresStartAction(
    kernelRoot,
    Object.values(kernelReceiptsById ?? {}),
  );
  const kernelCanOwnQuestion = !kernelRootState
    || ['pending', 'running', 'waiting'].includes(kernelRootState);
  const pendingQuestion = !rootTerminal
    && kernelCanOwnQuestion
    && projection.pendingUserQuestion?.rootId === rootId
    ? projection.pendingUserQuestion
    : undefined;
  // Questions, answers and the accepted plan stay inside the facilitator's
  // task card; low-level activity remains secondary detail in that same card.
  const visibleLanes = lanes;
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
    && !requiresStartAction
    && !pendingQuestion;
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
        plan={roomRootExecutionPlan(kernelRoot, Object.values(kernelReceiptsById ?? {}))}
        starting={startingRootIds.has(rootId)}
      />
    : null;
  const renderConversationMessage = (
    message: RoomMessageProjection,
    continuation = false,
  ) => {
    if (message.role === 'user') {
      return <RoomUserPost key={message.id} message={message} roomId={projection.roomId} />;
    }
    const lane = lanes.find((candidate) => candidate.messageIds.includes(message.id));
    const participant = room?.participants.find((item) => item.id === message.participantId);
    const persona = personas.find((item) => (
      item.roleId === participant?.roleId && item.version === participant.roleVersion
    ));
    const taskId = lane?.taskId || (lane?.dispatchId
      ? kernelDispatchesById?.[lane.dispatchId]?.taskId ?? ''
      : '');
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
        continuation={continuation}
        showEvidence={Boolean(roomTerminalPostLabels[message.postKind ?? ''])}
        turnStartedAtMs={turn.createdAtMs}
      />
      {message.id === finalAlignmentId ? startActionGate : null}
    </Fragment>;
  };
  const chronologicalStream = roomTurnChronologicalStream(
    visibleLanes,
    conversationMessages,
  );
  // A role owns one visual identity for the whole turn. Chronology may split
  // one role into A/B/A segments, but a later segment is still a continuation
  // instead of a second introduction with another avatar.
  const identityContinuationByItemKey = new Map<string, boolean>();
  const seenIdentityKeys = new Set<string>();
  for (const item of chronologicalStream) {
    const identityKey = item.kind === 'lane'
      ? item.lane.participantId || item.lane.sourceSessionId || item.lane.key
      : item.message.role === 'user'
        ? ''
        : item.message.participantId
          || lanes.find((candidate) => candidate.messageIds.includes(item.message.id))?.participantId
          || item.message.sourceSessionId;
    if (!identityKey) continue;
    identityContinuationByItemKey.set(item.key, seenIdentityKeys.has(identityKey));
    seenIdentityKeys.add(identityKey);
  }
  const firstLaneIndex = chronologicalStream.findIndex((item) => item.kind === 'lane');
  const streamBeforeWork = firstLaneIndex < 0
    ? chronologicalStream
    : chronologicalStream.slice(0, firstLaneIndex);
  const streamAfterWork = firstLaneIndex < 0
    ? []
    : chronologicalStream.slice(firstLaneIndex);
  return <article className="room-turn" data-turn-status={turn.status}>
    {streamBeforeWork.map((item) => (
      item.kind === 'message'
        ? renderConversationMessage(
            item.message,
            identityContinuationByItemKey.get(item.key) ?? false,
          )
        : null
    ))}
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
    {streamAfterWork.map((streamItem) => {
      if (streamItem.kind === 'message') {
        return renderConversationMessage(
          streamItem.message,
          identityContinuationByItemKey.get(streamItem.key) ?? false,
        );
      }
      const { activities: segmentActivities, includePersistentDetails, lane } = streamItem;
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
      const cardMessages = visibleMessages.filter(roomMessageBelongsInExecutionCard);
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
      ) || kernelRootFailed || (!explicitlyTerminal && turn.status === 'failed');
      const laneAborted = (
        lane.dispatchId
          ? (turn.abortedDispatchIds ?? []).includes(lane.dispatchId)
          : participantId
            ? (turn.abortedParticipantIds ?? []).includes(participantId)
            : false
      ) || kernelRootAborted || (!explicitlyTerminal && turn.status === 'aborted');
      // A terminal Root is authoritative even when a transient resume Dispatch
      // never appeared in the terminal-id lists.
      const laneTerminal = rootTerminal || explicitlyTerminal;
      const laneActive = !laneTerminal && !laneFailed && !laneAborted;
      const laneAction = rootTerminal
        ? undefined
        : lane.activities.find(roomActivityNeedsSessionAction);
      const laneTaskId = lane.taskId || (lane.dispatchId
        ? kernelDispatchesById?.[lane.dispatchId]?.taskId ?? ''
        : '');
      const laneIsCurrentTaskPhase = !laneTaskId
        || latestTaskLaneKeyByTaskId.get(laneTaskId) === lane.key;
      const laneTiming = roomLaneChronologyRange(lane, projection, turn);
      const laneFreshness = roomLaneFreshness(
        lane,
        projection,
        turn,
        nowMs,
        kernelSync,
        roomSyncState,
        laneTaskId && laneIsCurrentTaskPhase
          ? kernelTaskUpdatedAtMsById?.[laneTaskId]
          : undefined,
      );
      // A Task lane can contain several retry Dispatches. Historical attempts
      // remain visible in the body, but only the newest authoritative attempt
      // may drive the card header, motion, and terminal state.
      const authoritativeOutcomeMessages = lane.dispatchId
        ? cardMessages.filter((message) => message.dispatchId === lane.dispatchId)
        : cardMessages;
      const laneOutcome = authoritativeOutcomeMessages.reduce((outcome, message) => (
        roomTerminalPostLabels[message.postKind ?? '']
          ? message.postKind ?? outcome
          : outcome
      ), '');
      const laneOutcomeMessage = [...authoritativeOutcomeMessages].reverse().find((message) => (
        Boolean(roomTerminalPostLabels[message.postKind ?? ''])
      ));
      const laneComplete = (laneTerminal || Boolean(laneOutcome)) && !laneFailed && !laneAborted;
      const laneOperationallyActive = laneActive
        && !laneComplete
        && !laneAction
        && laneOutcome !== 'wait'
        && laneOutcome !== 'blocked';
      const laneMotionActive = laneOperationallyActive
        && laneFreshness.state === 'fresh';
      const authoritativeStatusLabel = laneAction
        ? '等待审阅'
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
          ? authoritativeStatusLabel
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
                  : laneActive
                    ? 'running'
                    : 'waiting';
      const laneTimingFreshness = !laneOperationallyActive
        ? { ...laneFreshness, state: 'fresh' as const, detail: '' }
        : laneFreshness;
      const laneTask = laneTaskId ? kernelTasksById?.[laneTaskId] : undefined;
      const laneSession = laneIsCurrentTaskPhase
        ? roomLaneSession(lane, laneTaskId, kernelSessionsById)
        : undefined;
      const laneTodo = roomLaneAuthoritativeTodo(lane, laneTask, laneSession);
      const showLaneTodo = Boolean(laneTodo && roomTodoHasUnsettledItems(laneTodo));
      const laneWork = roomLaneWorkSummary(
        segmentActivities,
        participant?.displayName,
        laneState,
        laneTask,
        laneOutcomeMessage,
      );
      const laneTodoSummary = showLaneTodo ? roomTaskTodoSummary(laneTodo) : '';
      const laneSubagents = laneTaskId && laneIsCurrentTaskPhase
        ? subagentsByTaskId[laneTaskId] ?? []
        : [];
      const includeCurrentTaskDetails = includePersistentDetails && laneIsCurrentTaskPhase;
      return <RoomLaneDisclosure
        active={laneMotionActive}
        collapsedPreview={laneComplete ? undefined : <RoomLaneCollapsedPreview
          activities={segmentActivities}
          participantName={participant?.displayName}
          workspaceTask={laneTask}
        />}
        defaultOpen={cardMessages.some((message) => (
          message.id === pendingQuestion?.postId || message.id === finalAlignmentId
        ))}
        data-motion={laneOperationallyActive ? laneFreshness.state : 'settled'}
        data-outcome={laneOutcome || undefined}
        data-state={laneState}
        key={streamItem.key}
        participantName={participant?.displayName ?? '协作伙伴'}
        summary={<>
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
              <span
                aria-label={laneMotionActive ? '正在接收实时进展' : '实时进展已暂停'}
                className="room-agent-lane__live-indicator"
                data-active={laneMotionActive}
              ><i /><i /><i /></span>
            </span>
            <strong className="room-agent-lane__task">{laneWork.title}</strong>
            <small className="room-agent-lane__progress">
              {laneWork.detail}{laneTodoSummary ? ` · ${laneTodoSummary}` : ''}
            </small>
          </span>
          <RoomLaneTiming
            freshness={laneTimingFreshness}
            nowMs={nowMs}
            startedAtMs={laneTiming.startedAtMs}
            endedAtMs={laneActive && !laneAction ? undefined : laneTiming.updatedAtMs}
          />
        </>}
      >
        {segmentActivities.length || (
          includePersistentDetails && laneTask && roomTaskWorkspaceLifecycleView(laneTask)
        ) ? <ActivityLog
          activities={segmentActivities}
          active={laneOperationallyActive}
          motionActive={laneMotionActive}
          updatesFresh={laneFreshness.state === 'fresh'}
          participantName={participant?.displayName}
          attention={laneState === 'failed' || laneState === 'aborted'}
          taskContext={laneTask}
          workspaceTask={includeCurrentTaskDetails ? laneTask : undefined}
          workspaceUpdatedAtMs={laneTaskId && laneIsCurrentTaskPhase
            ? kernelTaskUpdatedAtMsById?.[laneTaskId]
            : undefined}
        /> : null}
        {includeCurrentTaskDetails && laneSubagents.length ? <RoomTaskSubagentRuns
          heading={laneTask?.objective || `${participant?.displayName ?? '这位伙伴'}的临时协作者`}
          runs={laneSubagents}
        /> : null}
        {cardMessages.map((message) => <div
          className="room-agent-lane__commit room-conversation-post"
          data-post-kind={message.postKind || undefined}
          data-room-message-id={message.id}
          data-status={message.status}
          key={message.id}
        >
          {message.role === 'user' ? <div className="room-agent-lane__user-answer">
            <small>你的回答</small>
            <MarkdownBody text={message.text} />
          </div> : <RoomLanePost
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
            streamingMotion={laneMotionActive}
            turnStartedAtMs={turn.createdAtMs}
          />}
          {message.id === finalAlignmentId ? startActionGate : null}
        </div>)}
        {includeCurrentTaskDetails && laneComplete && laneTask?.workspaceDelivery
          ? <RoomTaskDeliveryDetails
              delivery={laneTask.workspaceDelivery}
              owner={participant?.displayName ?? '协作伙伴'}
            />
          : null}
        {includeCurrentTaskDetails && !lane.activities.length && laneActive && !messages.length ? <div className="room-agent-lane__waiting">
          {laneMotionActive ? <LoaderCircle size={14} /> : <Clock3 size={14} />}
          <span>{laneMotionActive
            ? participant
              ? `${participant.displayName} 已接手，正在准备`
              : '消息已经送达，正在请合适的伙伴回应'
            : laneFreshness.detail}
          </span>
        </div> : null}
        {includeCurrentTaskDetails && !terminalIssue && (laneFailed || laneAborted) && !cardMessages.length ? (
          <p className="room-agent-lane__failure">
            {laneFailed
              ? publicFailure
              : '这位伙伴的任务已经停止。'}
          </p>
        ) : null}
        {includeCurrentTaskDetails && showLaneTodo && laneTodo ? <RoomTaskTodoDetails
          live
          owner={participant?.displayName ?? '协作伙伴'}
          todo={laneTodo}
        /> : null}
      </RoomLaneDisclosure>;
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
    {pendingAction ? <SessionActionLink action={pendingAction} roomId={projection.roomId} /> : null}
  </article>;
}

function RoomParticipantPost({
  message,
  participant,
  persona,
  motionFresh,
  continuation,
  ...postProps
}: {
  message: RoomMessageProjection;
  participant?: TimelineParticipant;
  persona?: AgentPersonaV1;
  motionFresh: boolean;
  continuation: boolean;
  evidence?: RoomResponseEvidence;
  showEvidence: boolean;
  participants: readonly TimelineParticipant[];
  turnStartedAtMs: number;
  activeWait: boolean;
  pendingQuestion?: PendingRoomQuestion;
  onAnswerQuestion?: (
    question: PendingRoomQuestion,
    value: string,
    answerKind: RoomQuestionAnswerKind,
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
    data-continuation={continuation || undefined}
    data-room-message-id={message.id}
    data-status={message.status}
  >
    {!continuation ? <PersonaAvatar
        fallbackName={displayName}
        persona={persona}
        presence={presence}
        size="small"
      /> : null}
    <div>
      {!continuation ? <header>
        <strong>{displayName}</strong>
        {message.status === 'streaming'
          ? <small>{motionFresh ? '正在回复' : '状态可能过期'}</small>
          : null}
      </header> : null}
      <RoomLanePost
        {...postProps}
        message={message}
        streamingMotion={motionFresh}
      />
    </div>
  </article>;
}

interface RoomLaneDisclosureProps {
  active: boolean;
  collapsedPreview?: ReactNode;
  defaultOpen: boolean;
  participantName: string;
  summary: ReactNode;
  children: ReactNode;
  'data-continuation'?: boolean;
  'data-motion'?: string;
  'data-outcome'?: string;
  'data-state'?: string;
}

function RoomLaneDisclosure({
  active,
  collapsedPreview,
  defaultOpen,
  participantName,
  summary,
  children,
  ...attributes
}: RoomLaneDisclosureProps) {
  const [open, setOpen] = useState(defaultOpen);
  const userControlled = useRef(false);
  useEffect(() => {
    if (!userControlled.current) setOpen(defaultOpen);
  }, [defaultOpen]);
  return <details
    {...attributes}
    className="room-agent-lane"
    data-live={active || undefined}
    onToggle={(event) => setOpen(event.currentTarget.open)}
    open={open}
  >
    <summary
      aria-expanded={open}
      aria-label={`${open ? '收起' : '展开'}${participantName}的实时进展`}
      onClick={(event) => {
        event.preventDefault();
        userControlled.current = true;
        setOpen((current) => !current);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') userControlled.current = true;
      }}
    >
      {summary}
      <ChevronRight aria-hidden="true" className="room-agent-lane__disclosure" size={16} />
      {!open && collapsedPreview ? <div className="room-agent-lane__collapsed-preview">
        {collapsedPreview}
      </div> : null}
    </summary>
    <div className="room-agent-lane__body">{children}</div>
  </details>;
}

function RoomLaneCollapsedPreview({
  activities,
  participantName,
  workspaceTask,
}: {
  activities: RoomActivityProjection[];
  participantName?: string;
  workspaceTask?: RoomTaskV3;
}) {
  const visibleActivities = activities.filter((activity) => (
    textValue(activity.payload.sourceEventType) !== 'reasoning_summary'
    || textValue(activity.payload.source) === 'provider_reasoning_summary'
  ));
  const entries = roomActivityFeedEntries(visibleActivities).slice(-3);
  if (!entries.length) return null;
  return <ol aria-label={`${participantName ?? '这位伙伴'}最近的工作`}>
    {entries.map(({ activity, key, toolAttempts }) => {
      const sourceEventType = textValue(activity.payload.sourceEventType);
      const state = roomActivityDisplayStatus(activity);
      const summary = toolAttempts
        ? roomToolActivitySummary(
            activity,
            roomToolActivityResultView(activity).detailView,
            Math.max(0, toolAttempts.length - 1),
            toolAttempts.length,
            false,
          )
        : sourceEventType === 'reasoning_summary'
          ? roomReasoningSummary(activity, workspaceTask)
          : describeRoomActivity(activity, participantName).title;
      return <li data-state={state} key={`collapsed:${key}`}>
        <span aria-hidden="true">
          {state === 'running'
            ? <LoaderCircle size={13} />
            : state === 'failed'
              ? <X size={13} />
              : state === 'waiting'
                ? <Clock3 size={13} />
                : state === 'aborted'
                  ? <CircleStop size={13} />
                  : <CheckCircle2 size={13} />}
        </span>
        <strong>{summary}</strong>
        <RoomActivityTimestamp activity={activity} />
      </li>;
    })}
  </ol>;
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
}

function SessionActionLink({
  action,
  roomId,
}: {
  action: RoomSessionAction;
  roomId: string;
}) {
  return <a
    className="room-review-link room-review-link--turn"
    href={agentSessionHref(action.sessionId, roomId)}
  >
    <span>
      <strong>这轮协作正在等待审阅</strong>
      <small>伙伴已暂停；打开对应对话审阅计划或请求后会自动继续。</small>
    </span>
    <span>立即审阅 <ExternalLink size={13} /></span>
  </a>;
}

function roomLaneWorkSummary(
  activities: RoomActivityProjection[],
  participantName = '协作成员',
  laneState: string,
  workspaceTask?: RoomTaskV3,
  outcomeMessage?: RoomMessageProjection,
): { title: string; detail: string } {
  const digest = roomActivityDigest(activities, laneState === 'running');
  const orderedActivities = roomActivityFeedEntries(activities).map((entry) => entry.activity);
  if (laneState === 'failed' || laneState === 'aborted') {
    return {
      title: laneState === 'failed'
        ? `${participantName} 的任务未完成`
        : `${participantName} 的任务已停止`,
      detail: digest.detail,
    };
  }
  if (outcomeMessage) {
    const report = roomReportPreview(outcomeMessage.text);
    const label = roomTerminalPostLabels[outcomeMessage.postKind ?? ''] ?? '已完成';
    return {
      title: report || `${participantName}${label}`,
      detail: outcomeMessage.postKind === 'handoff'
        ? `${label} · 交接对象与时间见本框详情`
        : `${label} · 本轮面向你的结果已经记录`,
    };
  }
  if (laneState === 'completed') {
    const deliverySummary = roomPublicActivityText(
      workspaceTask?.workspaceDelivery?.resultSummary ?? '',
    );
    const expectedOutput = roomExpectedOutputText(workspaceTask?.expectedOutput ?? '');
    return {
      title: deliverySummary || `${participantName} 已完成本轮工作`,
      detail: expectedOutput
        ? `交付已返回 · ${expectedOutput}`
        : '交付已返回，结果与验证记录可在本框中查看',
    };
  }
  const latest = orderedActivities.at(-1);
  const activeFocus = laneState === 'running'
    ? [...orderedActivities].reverse().find((candidate) => (
        ['running', 'waiting'].includes(roomActivityDisplayStatus(candidate))
        && !roomActivityIsGenericStatus(candidate)
      ))
    : undefined;
  const latestMeaningful = [...orderedActivities].reverse().find((candidate) => (
    !roomActivityIsGenericStatus(candidate)
  ));
  const focus = activeFocus ?? latestMeaningful ?? latest;
  if (
    laneState === 'running'
    && focus
    && (
      focus.kind === 'route_decision'
      || textValue(focus.payload.sourceEventType) === 'route_decision'
    )
  ) {
    return {
      title: describeRoomActivity(focus, participantName).title,
      detail: digest.detail,
    };
  }
  if (
    laneState === 'running'
    && focus
    && textValue(focus.payload.sourceEventType) === 'reasoning_summary'
  ) {
    const expectedOutput = roomExpectedOutputText(workspaceTask?.expectedOutput ?? '');
    return {
      title: roomReasoningSummary(focus, workspaceTask),
      detail: `${digest.detail} · 工作摘要已更新 ${roomReasoningUpdateCount(focus)} 次${expectedOutput ? ` · 要交付：${expectedOutput}` : ''}`,
    };
  }
  if (
    laneState === 'running'
    && focus
    && roomActivityDisplayStatus(focus) === 'completed'
  ) {
    const objective = roomPublicActivityText(workspaceTask?.objective ?? '');
    const expectedOutput = roomExpectedOutputText(workspaceTask?.expectedOutput ?? '');
    return {
      title: objective
        ? `正在处理「${objective}」`
        : `${participantName} 正在继续任务`,
      detail: `${digest.detail}${expectedOutput ? ` · 要交付：${expectedOutput}` : ''}`,
    };
  }
  if (focus) {
    const sourceEventType = textValue(focus.payload.sourceEventType);
    const title = sourceEventType === 'reasoning_summary'
      ? roomReasoningSummary(focus, workspaceTask)
      : describeRoomActivity(focus, participantName).title;
    const expectedOutput = roomExpectedOutputText(workspaceTask?.expectedOutput ?? '');
    return {
      title,
      detail: `${digest.detail} · ${digest.title}${expectedOutput ? ` · 要交付：${expectedOutput}` : ''}`,
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

function roomActivityIsGenericStatus(activity: RoomActivityProjection): boolean {
  return activity.kind === 'participant_status'
    || textValue(activity.payload.sourceEventType) === 'participant_status';
}

function roomExpectedOutputText(value: string): string {
  const text = roomPublicActivityText(value);
  if (/^(?:这一步没有通过任务检查|提交的完成条件与当前任务不一致|还缺少能证明任务完成的验证结果|这个问题的选项没有准备完整)/u.test(text)) {
    return '';
  }
  return text;
}

function roomLaneSession(
  lane: RoomExecutionLane,
  taskId: string,
  sessionsById?: RoomKernelProjection['sessionsById'],
): PrivateSessionProjection | undefined {
  if (!sessionsById) return undefined;
  const exact = lane.sourceSessionId ? sessionsById[lane.sourceSessionId] : undefined;
  if (
    exact
    && (!lane.rootId || exact.rootId === lane.rootId)
    && (!lane.dispatchId || exact.dispatchId === lane.dispatchId)
  ) return exact;
  return Object.values(sessionsById)
    .filter((session) => (
      (!lane.rootId || session.rootId === lane.rootId)
      && (!lane.participantId || session.participantId === lane.participantId)
      && (
        (lane.dispatchId && session.dispatchId === lane.dispatchId)
        || (taskId && session.taskId === taskId)
      )
    ))
    .sort((left, right) => right.updatedAtMs - left.updatedAtMs)[0];
}

function roomLaneAuthoritativeTodo(
  lane: RoomExecutionLane,
  task: RoomTaskV3 | undefined,
  session: PrivateSessionProjection | undefined,
): PrivateSessionProjection['todo'] | undefined {
  const todo = session?.todo;
  const lineage = todo?.roomLineage;
  if (!session || !todo || !lineage) return undefined;
  if (
    todo.sessionId !== session.sessionId
    || lineage.schemaVersion !== 'wisdom-weasel.room-todo-lineage.v1'
    || lineage.rootId !== lane.rootId
    || lineage.sessionId !== session.sessionId
    || lineage.participantId !== lane.participantId
    || lineage.dispatchId !== lane.dispatchId
    || session.rootId !== lane.rootId
    || session.dispatchId !== lane.dispatchId
    || session.generation !== lineage.generation
  ) return undefined;
  if (
    task
    && (
      lineage.taskId !== task.taskId
      || session.taskId !== task.taskId
      || lineage.taskRevision !== task.revision
      || (
        task.ownershipRevision !== undefined
        && lineage.ownershipRevision !== task.ownershipRevision
      )
    )
  ) return undefined;
  if (
    session.workItemId
    && lineage.workItemId !== session.workItemId
  ) return undefined;
  return todo;
}

function roomTodoHasUnsettledItems(
  todo: NonNullable<PrivateSessionProjection['todo']>,
): boolean {
  const { total, completed, abandoned } = todo.counts;
  return total > completed + abandoned;
}

interface RoomActivityFeedEntry {
  key: string;
  activity: RoomActivityProjection;
  toolAttempts?: RoomActivityProjection[];
}

function roomActivityIsToolLifecycle(activity: RoomActivityProjection): boolean {
  return ['tool_started', 'tool_progress', 'tool_finished'].includes(
    textValue(activity.payload.sourceEventType),
  );
}

function roomToolAttemptIdentity(activity: RoomActivityProjection): string {
  return textValue(activity.payload.toolCallId) || activity.id;
}

function roomToolRetryParentIdentity(activity: RoomActivityProjection): string {
  const parent = textValue(activity.payload.retryOfToolCallId);
  return parent && parent !== roomToolAttemptIdentity(activity) ? parent : '';
}

/**
 * One provider retry sequence is one user-visible action. Lifecycle updates
 * for the same call replace each other, while distinct calls with the same
 * tool and public arguments remain available as attempt detail.
 */
function roomActivityFeedEntries(
  activities: RoomActivityProjection[],
): RoomActivityFeedEntry[] {
  const entries: RoomActivityFeedEntry[] = [];
  const toolEntryIndexByCallId = new Map<string, number>();
  for (const activity of activities) {
    if (!roomActivityIsToolLifecycle(activity)) {
      entries.push({ key: activity.id, activity });
      continue;
    }
    const attemptId = roomToolAttemptIdentity(activity);
    const retryParentId = roomToolRetryParentIdentity(activity);
    const existingIndex = toolEntryIndexByCallId.get(attemptId)
      ?? (retryParentId ? toolEntryIndexByCallId.get(retryParentId) : undefined);
    const existing = existingIndex === undefined ? undefined : entries[existingIndex];
    if (existingIndex === undefined || !existing?.toolAttempts) {
      entries.push({ key: `tool:${activity.id}`, activity, toolAttempts: [activity] });
      toolEntryIndexByCallId.set(attemptId, entries.length - 1);
      continue;
    }
    const attempts = existing.toolAttempts.some((attempt) => (
      roomToolAttemptIdentity(attempt) === attemptId
    ))
      ? existing.toolAttempts.map((attempt) => (
          roomToolAttemptIdentity(attempt) === attemptId ? activity : attempt
      ))
      : [...existing.toolAttempts, activity];
    entries[existingIndex] = {
      key: existing.key,
      activity,
      toolAttempts: attempts,
    };
    toolEntryIndexByCallId.set(attemptId, existingIndex);
  }
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((left, right) => (
      roomActivityPublicAtMs(left.entry.activity) - roomActivityPublicAtMs(right.entry.activity)
      || left.index - right.index
    ))
    .map(({ entry }) => entry);
}

function roomActivityPublicAtMs(activity: RoomActivityProjection): number {
  return activity.updatedAtMs ?? activity.createdAtMs;
}

function ActivityLog({
  activities,
  active,
  motionActive,
  updatesFresh,
  attention,
  participantName,
  taskContext,
  workspaceTask,
  workspaceUpdatedAtMs,
}: {
  activities: RoomActivityProjection[];
  active: boolean;
  motionActive: boolean;
  updatesFresh: boolean;
  attention: boolean;
  participantName?: string;
  taskContext?: RoomTaskV3;
  workspaceTask?: RoomTaskV3;
  workspaceUpdatedAtMs?: number;
}) {
  const workspaceView = workspaceTask
    ? roomTaskWorkspaceLifecycleView(workspaceTask)
    : undefined;
  const effectiveAttention = attention || workspaceView?.attention === true;
  const [arrivingActivityIds, setArrivingActivityIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const previousActivitySignatures = useRef<Map<string, string> | null>(null);
  const publicActivities = activities.filter((activity) => {
    if (textValue(activity.payload.sourceEventType) !== 'reasoning_summary') return true;
    return textValue(activity.payload.source) === 'provider_reasoning_summary';
  });
  const feedEntries = roomActivityFeedEntries(publicActivities);
  const activityContentKey = publicActivities.map((activity) => (
    `${activity.id}:${activity.status}:${activity.updatedAtMs ?? activity.createdAtMs}:${activity.summary}`
  )).join('\u001f');
  const workspaceContentKey = workspaceTask && workspaceView
    ? `workspace:${workspaceTask.taskId}:${workspaceTask.revision}:${workspaceTask.workspaceLifecycleState}:${workspaceTask.workspaceAttentionRequired ?? ''}`
    : '';
  const contentKey = `${activityContentKey}\u001f${workspaceContentKey}`;
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
  if (!publicActivities.length && !workspaceView) return null;
  const digest = publicActivities.length
    ? roomActivityDigest(publicActivities, active)
    : {
        title: workspaceView?.title ?? '工作区进展',
        detail: '1 条权威任务更新',
  };
  const changedFiles = roomChangedFileSummary(publicActivities);
  return <section
    aria-label={`实时进展与运行记录：${participantName ?? '协作成员'}`}
    className="room-agent-lane__activity"
    data-motion={motionActive ? 'fresh' : 'paused'}
    data-state={effectiveAttention ? 'attention' : active ? 'running' : 'settled'}
  >
    <header className="room-agent-lane__activity-heading">
      <Wrench size={14} />
      <span>
        <strong>{digest.title}</strong>
        <small>{digest.detail}</small>
      </span>
    </header>
    {changedFiles.length ? <ul
      aria-label={`${participantName ?? '协作成员'}改动的文件`}
      className="room-agent-lane__changed-files"
    >{changedFiles.map((file) => <li key={file.name}>
      <code>{file.name}</code>
      {file.hasCounts ? <span>
        <b>+{file.additions}</b>
        <i>−{file.deletions}</i>
      </span> : <small>已更新</small>}
    </li>)}</ul> : null}
    <div
      className="room-agent-lane__activity-feed"
      data-layout="continuous"
    >{feedEntries.map((entry) => {
      const { activity } = entry;
      const displayStatus = roomActivityDisplayStatus(activity);
      const sourceEventType = textValue(activity.payload.sourceEventType);
      const arriving = updatesFresh && (
        arrivingActivityIds.has(activity.id)
        || entry.toolAttempts?.some((attempt) => arrivingActivityIds.has(attempt.id)) === true
      );
      if (entry.toolAttempts) {
        return <RoomToolActivity
          activity={activity}
          arriving={arriving}
          attempts={entry.toolAttempts}
          recovering={active && activity.status === 'failed'}
          key={entry.key}
        />;
      }
      if (sourceEventType === 'reasoning_summary') {
        const summary = roomReasoningSummary(activity, taskContext ?? workspaceTask);
        const updateCount = roomReasoningUpdateCount(activity);
        return <article
          className="room-reasoning-summary"
          data-arriving={arriving || undefined}
          data-state={displayStatus}
          key={activity.id}
        >
          <Sparkles aria-hidden="true" size={14} />
          <span>
            <small><span className="room-activity-provenance">实时进展</span> · 工作摘要{updateCount > 1 ? ` · 已更新 ${updateCount} 次` : ''} · <RoomActivityTimestamp activity={activity} /></small>
            <strong>{summary}</strong>
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
      arriving={updatesFresh && arrivingActivityIds.has(`workspace:${workspaceTask.taskId}`)}
      task={workspaceTask}
      updatedAtMs={workspaceUpdatedAtMs}
      view={workspaceView}
    /> : null}
    </div>
  </section>;
}

interface RoomChangedFileSummary {
  name: string;
  identity: string;
  displaySegments: string[];
  additions: number;
  deletions: number;
  hasCounts: boolean;
}

const roomMutationTools = new Set([
  'write',
  'edit',
]);

function roomChangedFileSummary(
  activities: RoomActivityProjection[],
): RoomChangedFileSummary[] {
  const files = new Map<string, RoomChangedFileSummary>();
  for (const activity of activities) {
    if (
      textValue(activity.payload.sourceEventType) !== 'tool_finished'
      || activity.status !== 'completed'
      || !roomMutationTools.has(canonicalToolId(textValue(activity.payload.toolName)))
    ) continue;
    const args = objectValue(activity.payload.arguments);
    const result = objectValue(activity.payload.result);
    const changedFiles = Array.isArray(result.changedFiles)
      ? result.changedFiles.map(objectValue).filter((item) => Object.keys(item).length > 0)
      : [];
    const candidates = changedFiles.length ? changedFiles : [result];
    for (const candidate of candidates) {
      const rawName = textValue(
        candidate.fileName
        || candidate.path
        || (changedFiles.length ? '' : args.fileName || args.path),
      );
      const normalizedPath = rawName.trim().replace(/\\/gu, '/').replace(/\/{2,}/gu, '/').replace(/\/+$/u, '');
      const pathSegments = normalizedPath.split('/').filter((segment) => (
        Boolean(segment) && segment !== '.' && segment !== '..'
      ));
      const name = pathSegments.at(-1) ?? '';
      const identity = pathSegments.join('/');
      if (!name || !identity) continue;
      const additions = nonNegativeCount(candidate.additions);
      const deletions = nonNegativeCount(candidate.deletions);
      const hasCounts = additions !== null || deletions !== null;
      const existing = files.get(identity) ?? {
        name,
        identity,
        displaySegments: publicRoomFileSegments(normalizedPath, pathSegments),
        additions: 0,
        deletions: 0,
        hasCounts: false,
      };
      existing.additions += additions ?? 0;
      existing.deletions += deletions ?? 0;
      existing.hasCounts ||= hasCounts;
      files.set(identity, existing);
    }
  }
  const summaries = [...files.values()];
  const sameBasename = new Map<string, RoomChangedFileSummary[]>();
  for (const summary of summaries) {
    sameBasename.set(summary.name, [...(sameBasename.get(summary.name) ?? []), summary]);
  }
  return summaries.map((summary) => ({
    ...summary,
    name: shortestUniqueFileSuffix(summary, sameBasename.get(summary.name) ?? [summary]),
  }));
}

function shortestUniqueFileSuffix(
  file: RoomChangedFileSummary,
  peers: RoomChangedFileSummary[],
): string {
  for (let depth = 1; depth <= file.displaySegments.length; depth += 1) {
    const suffix = file.displaySegments.slice(-depth).join('/');
    if (peers.every((peer) => (
      peer.identity === file.identity
      || peer.displaySegments.slice(-depth).join('/') !== suffix
    ))) return suffix;
  }
  return `${file.displaySegments.join('/')} · ${nonSensitiveFileDisambiguator(file.identity)}`;
}

const roomPublicFileAnchors = new Set([
  'control-center-web',
  'dataset',
  'docs',
  'eval',
  'integrations',
  'macos',
  'rag_ime',
  'release',
  'scripts',
  'squirrel-patches',
  'src',
  'test',
  'tests',
]);

function publicRoomFileSegments(
  normalizedPath: string,
  pathSegments: string[],
): string[] {
  const absolute = normalizedPath.startsWith('/') || /^[A-Za-z]:\//u.test(normalizedPath);
  if (!absolute) return pathSegments;
  const anchorIndex = pathSegments.findIndex((segment) => roomPublicFileAnchors.has(segment));
  return anchorIndex >= 0 ? pathSegments.slice(anchorIndex) : pathSegments.slice(-1);
}

function nonSensitiveFileDisambiguator(identity: string): string {
  let hash = 2_166_136_261;
  for (let index = 0; index < identity.length; index += 1) {
    hash ^= identity.charCodeAt(index);
    hash = Math.imul(hash, 16_777_619);
  }
  return (hash >>> 0).toString(36).padStart(6, '0').slice(0, 6);
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function nonNegativeCount(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
    ? value
    : null;
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

const roomPublicWorkSummaries = {
  alignment: '需求与交付边界梳理有新进展',
  implementation: '当前任务推进有新进展',
  review: '结果与验收条件复核有新进展',
  closure: '本轮结果整理有新进展',
  general: '当前工作有新进展',
} as const;

function roomReasoningSummary(
  activity: RoomActivityProjection,
  workspaceTask?: RoomTaskV3,
): string {
  const requestedKind = textValue(activity.payload.publicSummaryKind);
  const summaryKind = (
    activity.payload.publicSummaryVersion === 'room-work-summary.v1'
    && requestedKind in roomPublicWorkSummaries
  ) ? requestedKind as keyof typeof roomPublicWorkSummaries : 'general';
  const objective = roomPublicActivityText(workspaceTask?.objective ?? '');
  if (objective) {
    return {
      alignment: `正在整理「${objective}」的需求与执行方案`,
      implementation: `正在处理「${objective}」`,
      review: `正在检查「${objective}」是否达到要求`,
      closure: `正在整理「${objective}」的结果和验证`,
      general: `正在继续「${objective}」`,
    }[summaryKind];
  }
  return {
    alignment: '正在整理你的需求和执行方案',
    implementation: '正在推进当前功能',
    review: '正在核对结果是否符合要求',
    closure: '正在整理结果和验证',
    general: '正在整理下一步',
  }[summaryKind];
}

function roomReasoningUpdateCount(activity: RoomActivityProjection): number {
  const count = Number(activity.payload.updateCount);
  const historyCount = Array.isArray(activity.payload.reasoningHistory)
    ? activity.payload.reasoningHistory.length
    : 0;
  return Number.isInteger(count) && count > 0 ? count : Math.max(1, historyCount);
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
    answerKind: RoomQuestionAnswerKind,
  ) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const visibleBlocks = roomVisibleBlocks(message.message?.blocks ?? []);
  const reportLabel = roomPostReportLabel(message);
  const meaningfulText = roomPostMeaningfulText(message.text);
  if (!message.question && !visibleBlocks.length && !meaningfulText) return null;
  const collapsible = roomPostShouldCollapse(message, visibleBlocks);
  const questionIsAuthoritative = Boolean(
    message.question?.status === 'pending'
    && pendingQuestion
    && message.id === pendingQuestion.postId
    && message.rootId === pendingQuestion.rootId
    && onAnswerQuestion
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
            ? (value, answerKind) => onAnswerQuestion(
                pendingQuestion,
                value,
                answerKind,
              )
            : undefined}
        />
      </div>
    : visibleBlocks.length
      ? <AgentBlocks blocks={visibleBlocks} sessionId={message.message?.sessionId ?? message.sourceSessionId} />
      : meaningfulText
        ? <MarkdownBody text={meaningfulText} />
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
    {showEvidence && message.status !== 'streaming' && roomResponseEvidenceIsComplete(evidence)
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
  if (
    !['handoff', 'wait', 'blocked'].includes(message.postKind ?? '')
    || (message.postKind === 'wait' && Boolean(message.question))
  ) return null;
  const targetNames = (message.mentionedParticipantIds ?? [])
    .map((participantId) => (
      participants.find((participant) => participant.id === participantId)?.displayName
    ))
    .filter((value): value is string => Boolean(value));
  const target = targetNames.join('、');
  const sourceParticipant = participants.find((participant) => (
    participant.id === message.participantId
    || participant.id === message.authorActorRef
    || `participant:${participant.id}` === message.authorActorRef
  ));
  const source = sourceParticipant?.displayName ?? '协作伙伴';
  const title = message.postKind === 'handoff'
    ? target
      ? `${source} → ${target}`
      : `${source} → 交接目标待确认`
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

type CompleteRoomResponseEvidence = RoomResponseEvidence & {
  usage: RoomResponseUsage;
  usageReported: true;
  cacheUsageReported: true;
};

function roomResponseEvidenceIsComplete(
  evidence: RoomResponseEvidence | undefined,
): evidence is CompleteRoomResponseEvidence {
  return Boolean(
    evidence?.provider
    && evidence.model
    && evidence.usage
    && evidence.usageReported
    && evidence.cacheUsageReported
  );
}

function roomResponseEvidenceForPost(
  message: RoomMessageProjection,
  activities: RoomActivityProjection[],
): CompleteRoomResponseEvidence | undefined {
  const messageDispatchId = textValue(message.dispatchId);
  if (!messageDispatchId) return undefined;

  for (const preferredType of ['response_evidence', 'message_completed'] as const) {
    for (let index = activities.length - 1; index >= 0; index -= 1) {
      const activity = activities[index];
      if (
        !activity
        || textValue(activity.payload.sourceEventType) !== preferredType
        || textValue(activity.payload.dispatchId) !== messageDispatchId
        || textValue(activity.payload.responsePostId) !== message.id
      ) continue;

      const usageReported = activity.payload.usageReported === true;
      const evidence: RoomResponseEvidence = {
        usage: usageReported
          ? normalizeRoomResponseUsage(activity.payload.usage)
          : undefined,
        usageReported,
        cacheUsageReported: (
          usageReported
          && activity.payload.cacheUsageReported === true
        ),
        provider: textValue(activity.payload.provider),
        model: textValue(activity.payload.model),
        runtimeTurnId: textValue(activity.payload.runtimeTurnId),
        sourceSessionId: activity.sourceSessionId || message.sourceSessionId,
      };
      if (roomResponseEvidenceIsComplete(evidence)) return evidence;
    }
  }
  return undefined;
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
  evidence: CompleteRoomResponseEvidence;
}) {
  const contextHref = evidence.sourceSessionId && evidence.runtimeTurnId
    ? `#/context-debug?sessionId=${encodeURIComponent(evidence.sourceSessionId)}&turnId=${encodeURIComponent(evidence.runtimeTurnId)}`
    : '';
  return <footer aria-label="回复运行记录" className="room-response-evidence">
    <small className="room-response-evidence__source">运行记录</small>
    <small
      className="room-response-model"
      data-state="reported"
      title={`provider=${evidence.provider}, model=${evidence.model}`}
    >
      {evidence.provider} · {evidence.model}
    </small>
    <RoomResponseUsageFooter usage={evidence.usage} />
    {contextHref ? <a href={contextHref}>
      <Braces aria-hidden="true" size={12} />
      查看本轮上下文
    </a> : null}
  </footer>;
}

function RoomResponseUsageFooter({
  usage,
}: {
  usage: RoomResponseUsage;
}) {
  const cacheLabel = `缓存读取 ${usage.cacheRead} tokens，缓存写入 ${usage.cacheWrite} tokens`;
  return <small
    aria-label={`输入 ${usage.input} tokens，输出 ${usage.output} tokens，${cacheLabel}`}
    className="room-response-usage"
    data-cache-hit={usage.cacheRead > 0}
    data-cache-reported="true"
    title={`input=${usage.input}, output=${usage.output}, cacheRead=${usage.cacheRead}, cacheWrite=${usage.cacheWrite}`}
  >
    <span>输入 {formatTokenCount(usage.input)}</span>
    <span>输出 {formatTokenCount(usage.output)}</span>
    <>
      <span>{usage.cacheRead > 0 ? '缓存命中' : '缓存读'} {formatTokenCount(usage.cacheRead)}</span>
      <span>写 {formatTokenCount(usage.cacheWrite)}</span>
    </>
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

function roomActivityProvenanceLabel(activity: RoomActivityProjection): '实时进展' | '运行记录' {
  const sourceEventType = textValue(activity.payload.sourceEventType);
  const activityKind = textValue(activity.payload.activityKind);
  if (
    ['reasoning_summary', 'current_progress', 'progress'].includes(sourceEventType)
    || ['intercom', 'work'].includes(activityKind)
  ) return '实时进展';
  return '运行记录';
}

function roomActivityDigest(
  activities: RoomActivityProjection[],
  workActive = false,
): { title: string; detail: string } {
  const displayActivities = roomActivityFeedEntries(activities).map((entry) => entry.activity);
  const labels = displayActivities.flatMap((activity) => {
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
  const counts = displayActivities.reduce((result, activity) => {
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
      ? workActive
        ? `${counts.completed} 个步骤已返回 · 正在继续`
        : '所有步骤已返回'
      : counts.completed
        ? `${counts.completed} 个步骤已返回`
        : '',
  ].filter(Boolean);
  return {
    title,
    detail: `${displayActivities.length} 个步骤 · ${states.join(' · ')}`,
  };
}

function roomToolActivityResultView(activity: RoomActivityProjection): {
  detailView: PublicToolResultView;
  safeResult: unknown;
} {
  const payload = activity.payload;
  const safeResult = payload.result;
  const publicResult = safeResult && typeof safeResult === 'object' && !Array.isArray(safeResult)
    ? safeResult as Record<string, unknown>
    : {};
  const error = textValue(payload.error);
  const projectedArguments = payload.arguments && typeof payload.arguments === 'object' && !Array.isArray(payload.arguments)
    ? payload.arguments as Record<string, unknown>
    : {};
  const view = publicToolResultView({
    kind: textValue(payload.sourceEventType) || activity.kind,
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
  return {
    detailView: roomPublicToolResultView({
      ...view,
      request: view.request.length ? view.request : requestFields,
      fields: [
        ...view.fields,
        ...resultFields.filter((field) => (
          !view.fields.some((existingField) => existingField.id === field.id)
        )),
      ],
    }),
    safeResult,
  };
}

function roomToolActivitySummary(
  activity: RoomActivityProjection,
  detailView: PublicToolResultView,
  retryCount: number,
  attemptCount: number,
  recovering: boolean,
): string {
  const toolId = detailView.toolId || canonicalToolId(textValue(activity.payload.toolName));
  const targetFile = detailView.request.find((field) => (
    field.id === 'path' || field.id === 'file'
  ))?.value || detailView.fields.find((field) => field.id === 'file')?.value || '';
  const activeToolSummary = toolId === 'read'
    ? `正在读取${targetFile ? ` ${targetFile}` : '文件'}`
    : toolId === 'edit'
      ? `正在编辑${targetFile ? ` ${targetFile}` : '文件'}`
      : toolId === 'write'
        ? `正在写入${targetFile ? ` ${targetFile}` : '文件'}`
        : toolId === 'bash'
          ? '命令正在运行，等待新的输出'
          : detailView.summary || `${detailView.toolLabel}进行中`;
  if (recovering) return `正在恢复：${detailView.toolLabel}`;
  if (retryCount) {
    if (activity.status === 'completed') return `${detailView.toolLabel}重试 ${retryCount} 次后成功`;
    if (activity.status === 'running') return `${detailView.toolLabel}正在第 ${attemptCount} 次尝试`;
    return `${detailView.toolLabel}已尝试 ${attemptCount} 次，仍未完成`;
  }
  if (activity.status === 'running') return activeToolSummary;
  if (activity.status === 'failed') return `${detailView.toolLabel}执行失败`;
  if (activity.status === 'aborted') return `${detailView.toolLabel}已停止`;
  return detailView.summary || detailView.toolLabel;
}


function RoomToolActivity({
  activity,
  arriving,
  attempts,
  recovering,
}: {
  activity: RoomActivityProjection;
  arriving: boolean;
  attempts: RoomActivityProjection[];
  recovering: boolean;
}) {
  const payload = activity.payload;
  const approvalId = textValue(payload.approvalId);
  const sourceEventType = textValue(payload.sourceEventType);
  const initiallyActive = Boolean(
    (approvalId && ['running', 'waiting'].includes(activity.status))
    || activity.status === 'running');
  const [open, setOpen] = useState(initiallyActive);
  const autoOpenedRef = useRef(initiallyActive);
  const userControlledDisclosureRef = useRef(false);
  useEffect(() => {
    const active = Boolean(
      (approvalId && ['running', 'waiting'].includes(activity.status))
      || activity.status === 'running');
    if (active) {
      autoOpenedRef.current = true;
      if (!userControlledDisclosureRef.current) setOpen(true);
      return;
    }
    if (autoOpenedRef.current && !userControlledDisclosureRef.current) {
      setOpen(false);
    }
  }, [activity.status, approvalId]);
  const { detailView, safeResult } = roomToolActivityResultView(activity);
  const approvalDescription = approvalId ? describeRoomActivity(activity) : null;
  const retryCount = Math.max(0, attempts.length - 1);
  const toolId = detailView.toolId || canonicalToolId(textValue(payload.toolName));
  const basicToolKind = ['read', 'edit', 'write', 'bash'].includes(toolId)
    ? toolId
    : 'standard';
  const editing = roomMutationTools.has(toolId);
  const editStarted = sourceEventType === 'tool_started'
    || (Array.isArray(payload.progressHistory) && payload.progressHistory.some((entry) => (
      textValue(objectValue(entry).kind) === 'tool_started'
    )));
  const editActive = editing
    && activity.status === 'running'
    && Boolean(textValue(payload.toolCallId))
    && editStarted
    && ['tool_started', 'tool_progress'].includes(sourceEventType);
  const toolStreaming = basicToolKind !== 'standard'
    && activity.status === 'running'
    && ['tool_started', 'tool_progress'].includes(sourceEventType);
  const mutationAwaitingDiff = toolStreaming && editing;
  const showArtifacts = hasToolArtifacts(detailView.artifacts) && !mutationAwaitingDiff;
  const showRunningPreview = toolStreaming
    && (!detailView.output || mutationAwaitingDiff);
  const targetFile = detailView.request.find((field) => (
    field.id === 'path' || field.id === 'file'
  ))?.value || detailView.fields.find((field) => field.id === 'file')?.value || '';
  const summary = roomToolActivitySummary(
    activity,
    detailView,
    retryCount,
    attempts.length,
    recovering,
  );
  return (
    <details
      className="room-agent-activity room-agent-activity--tool"
      data-arriving={arriving || undefined}
      data-edit-active={editActive || undefined}
      data-state={recovering ? 'waiting' : activity.status}
      data-tool-kind={basicToolKind}
      open={open}
    >
      <summary
        aria-expanded={open}
        onClick={(event) => {
          userControlledDisclosureRef.current = true;
          toggleDisclosurePreservingAnchor(event, setOpen);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            userControlledDisclosureRef.current = true;
          }
          toggleDisclosureOnKeyPreservingAnchor(event, setOpen);
        }}
      >
        <span className="room-agent-activity__state" aria-hidden="true">
          {recovering
            ? <Clock3 size={14} />
            : activity.status === 'running'
            ? editActive ? <Braces size={14} /> : <LoaderCircle size={14} />
            : activity.status === 'failed'
              ? <X size={14} />
              : activity.status === 'waiting'
                ? <Clock3 size={14} />
                : activity.status === 'aborted'
                  ? <CircleStop size={14} />
                  : <CheckCircle2 size={14} />}
        </span>
        <span>
          <strong>{summary}</strong>
          <small><span className="room-activity-provenance">运行记录</span> · {detailView.toolLabel} · {recovering ? '伙伴正在修正并准备重试' : roomToolStatusLabel(activity.status)}{retryCount ? ` · ${attempts.length} 次尝试` : roomToolProgressCount(payload) > 1 ? ` · ${roomToolProgressCount(payload)} 次更新` : ''} · <RoomActivityTimestamp activity={activity} /></small>
          {editActive ? <span
            aria-label="正在接收文件编辑进度"
            className="room-agent-edit-progress"
            role="status"
          ><i /><i /><i /></span> : null}
        </span>
        <ChevronRight aria-hidden="true" size={14} />
      </summary>
      {open ? (
        <div className="room-agent-activity__details">
          {retryCount ? <section
            aria-label={`${detailView.toolLabel}尝试记录`}
            className="room-agent-tool-attempts"
          >
            <strong>尝试记录</strong>
            {attempts.map((attempt, index) => {
              const attemptError = roomPublicActivityText(textValue(attempt.payload.error));
              const finalAttempt = index === attempts.length - 1;
              return <article
                className="room-agent-tool-attempt"
                data-state={attempt.status}
                key={`${roomToolAttemptIdentity(attempt)}:${index}`}
              >
                {attempt.status === 'completed'
                  ? <CheckCircle2 aria-hidden="true" size={13} />
                  : attempt.status === 'failed'
                    ? <X aria-hidden="true" size={13} />
                    : attempt.status === 'running'
                      ? <LoaderCircle aria-hidden="true" size={13} />
                      : <Clock3 aria-hidden="true" size={13} />}
                <span>
                  <strong>{finalAttempt ? '最终尝试' : `第 ${index + 1} 次尝试`}</strong>
                  <small>{attempt.status === 'completed'
                    ? '最终提交成功'
                    : attemptError || '这次尝试没有完成，系统随后自动重试。'}</small>
                </span>
                <RoomActivityTimestamp activity={attempt} />
              </article>;
            })}
          </section> : null}
          {showArtifacts ? (
            <ToolArtifactOutput artifacts={detailView.artifacts} autoExpandDiff={activity.status === 'completed'} />
          ) : null}
          {!showArtifacts && detailView.request.length ? <PublicToolRequest view={detailView} /> : null}
          {showRunningPreview ? (
            <ToolRunningPreview target={targetFile} toolId={basicToolKind} />
          ) : null}
          {!showArtifacts && !mutationAwaitingDiff && detailView.output ? (
            <PublicToolOutput streaming={toolStreaming} view={detailView} />
          ) : null}
          {!showArtifacts && detailView.preview ? <SemanticToolPreview preview={detailView.preview} /> : null}
          {!showArtifacts && detailView.fields.length ? <PublicToolFields view={detailView} /> : null}
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
          {activity.status === 'running' && safeResult === undefined && !showRunningPreview ? (
            <p className="room-agent-activity__unavailable">工具尚未返回结果。</p>
          ) : activity.status === 'aborted' && safeResult === undefined ? (
            <p className="room-agent-activity__unavailable">这个步骤已随本轮任务停止，没有返回公开结果。</p>
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
  entrySurface: '具体入口',
  primaryInteraction: '关键操作',
  observableCompletion: '完成标志',
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
  decision: '下一步',
  publicSummary: '给用户的说明',
  question: '询问内容',
  resumeCondition: '继续条件',
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

function roomLatestTaskLaneKeys(
  lanes: RoomExecutionLane[],
  projection: RoomProjectionState,
  dispatchesById?: RoomKernelProjection['dispatchesById'],
): Map<string, string> {
  const latestByTaskId = new Map<string, {
    executionPhase: number;
    key: string;
    sequence?: number;
    updatedAtMs: number;
  }>();
  for (const lane of lanes) {
    const taskId = lane.taskId || (lane.dispatchId
      ? dispatchesById?.[lane.dispatchId]?.taskId ?? ''
      : '');
    if (!taskId) continue;
    const range = roomLaneChronologyRange(lane, projection);
    const current = latestByTaskId.get(taskId);
    if (
      !current
      || lane.executionPhase > current.executionPhase
      || (
        lane.executionPhase === current.executionPhase
        && compareRoomLaneRecency(current, range) < 0
      )
    ) {
      latestByTaskId.set(taskId, {
        executionPhase: lane.executionPhase,
        key: lane.key,
        sequence: range.latestSequence,
        updatedAtMs: range.updatedAtMs,
      });
    }
  }
  return new Map([...latestByTaskId].map(([taskId, value]) => [taskId, value.key]));
}

function roomLaneChronologyRange(
  lane: RoomExecutionLane,
  projection: RoomProjectionState,
  fallbackTurn?: RoomTurnProjection,
): { startedAtMs: number; updatedAtMs: number; latestSequence?: number } {
  const records = [
    ...lane.activities.map((activity) => ({
      sequence: activity.sequence,
      startedAtMs: activity.createdAtMs,
      updatedAtMs: activity.updatedAtMs ?? activity.createdAtMs,
    })),
    ...lane.messageIds.flatMap((messageId) => {
      const message = projection.messagesById[messageId];
      return message ? [{
        sequence: message.chronology?.roomEventSequence ?? message.sequence,
        startedAtMs: message.chronology?.createdAtMs ?? message.createdAtMs,
        updatedAtMs: message.completedAtMs ?? message.createdAtMs,
      }] : [];
    }),
  ];
  if (!records.length) {
    const fallbackAtMs = fallbackTurn?.updatedAtMs ?? Date.now();
    return {
      startedAtMs: fallbackTurn?.createdAtMs ?? fallbackAtMs,
      updatedAtMs: fallbackAtMs,
    };
  }
  const sequences = records.flatMap((record) => (
    record.sequence === undefined ? [] : [record.sequence]
  ));
  return {
    startedAtMs: Math.min(...records.map((record) => record.startedAtMs)),
    updatedAtMs: Math.max(...records.map((record) => record.updatedAtMs)),
    ...(sequences.length ? { latestSequence: Math.max(...sequences) } : {}),
  };
}

function compareRoomLaneRecency(
  left: { sequence?: number; updatedAtMs: number },
  right: { sequence?: number; updatedAtMs: number },
): number {
  if (left.sequence !== undefined || right.sequence !== undefined) {
    if (left.sequence === undefined) return -1;
    if (right.sequence === undefined) return 1;
    if (left.sequence !== right.sequence) return left.sequence - right.sequence;
  }
  return left.updatedAtMs - right.updatedAtMs;
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
      detail: '仍在处理，暂时没有新的公开进展；如有短暂中断会自动恢复',
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
  const rawToolName = textValue(payload.toolName);
  const toolName = publicToolName(rawToolName, textValue(payload.displayName));
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
    const summary = roomReasoningSummary(activity);
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
    if (sessionId) return { sessionId };
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
      if (sessionId) return { sessionId };
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
    && roomBlockHasPublicContent(block)
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

function roomBlockHasPublicContent(
  block: NonNullable<RoomMessageProjection['message']>['blocks'][number],
): boolean {
  if (block.type !== 'citation' && block.type !== 'reference') return true;
  const data = block.data;
  return [
    data.title,
    data.label,
    data.name,
    data.source,
    data.domain,
    data.publisher,
    data.excerpt,
    data.snippet,
    data.description,
    data.href,
    data.url,
    data.uri,
  ].some((value) => typeof value === 'string' && value.trim().length > 0);
}

function roomPostMeaningfulText(value: string): string {
  const text = value.trim();
  if (!text) return '';
  if (/^(?:进度更新|当前任务推进有新进展|当前工作有新进展)[。.!！]?$/u.test(text)) return '';
  return text;
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

function agentSessionHref(sessionId: string, roomId: string): string {
  const params = new URLSearchParams({ session: sessionId });
  if (roomId) params.set('returnRoom', roomId);
  return `#/agent?${params}`;
}
