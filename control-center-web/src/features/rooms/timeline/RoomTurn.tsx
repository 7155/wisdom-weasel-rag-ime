import {
  CheckCircle2,
  CircleAlert,
  ChevronRight,
  CircleStop,
  Clock3,
  ExternalLink,
  LoaderCircle,
  Route,
  RotateCcw,
  Wrench,
  X,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

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
import { publicAgentErrorText } from '@/features/agent/public-error';
import { AgentBlocks, MarkdownBody } from '@/features/agent/timeline/BlockRenderer';
import {
  PublicToolError,
  PublicToolFields,
  PublicToolOutput,
  PublicToolRequest,
} from '@/features/agent/timeline/ActivitySummary';
import { toggleDisclosurePreservingAnchor } from '@/features/agent/timeline/disclosure-anchor';
import { publicToolResultView } from '@/features/agent/timeline/public-tool-result';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { publicToolName } from '@/features/agent/tool-presentation';
import {
  roomActivityNeedsSessionAction,
  selectRoomTurnExecution,
  type RoomExecutionLane,
} from '../runtime/room-execution-lanes';
import { roomProjection, useRoomLiveStore } from '../state/live-store';
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
  onAbortTurn?: (rootId: string) => void;
  retryingRootIds?: ReadonlySet<string>;
  retryingTurn?: boolean;
  onRetryTurn?: (message: string) => void;
  onRetryRoot?: (rootId: string) => void;
}

const roomTerminalPostLabels: Readonly<Record<string, string>> = {
  result: '已完成',
  handoff: '已转交',
  wait: '等待继续',
  blocked: '已阻塞',
};

function roomVisibleLaneMessages(
  messages: RoomMessageProjection[],
): RoomMessageProjection[] {
  let latestTerminalId = '';
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]!;
    if (
      message.projectionKind !== 'execution'
      && roomTerminalPostLabels[message.postKind ?? '']
    ) {
      latestTerminalId = message.id;
      break;
    }
  }
  return messages.filter((message) => (
    message.projectionKind === 'execution'
    || !roomTerminalPostLabels[message.postKind ?? '']
    || message.id === latestTerminalId
  ));
}

function roomPostReportLabel(message: RoomMessageProjection): string {
  if (message.projectionKind === 'execution') return '';
  if (message.postKind === 'result') return '任务汇报';
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
  abortingTurnIds = new Set(),
  retryingRootIds = new Set(),
  onAbortTurn,
  retryingTurn = false,
  onRetryTurn,
  onRetryRoot,
}: RoomTurnProps) {
  useRoomLiveStore((state) => (
    providedProjection ? 0 : state.turnRevisions[roomId]?.[turnId] ?? 0
  ));
  const projection = providedProjection ?? roomProjection(roomId);
  const turn = projection.turnsById[turnId];
  const previousTurnStatus = usePrevious(turn?.status);
  // Room/session lifecycle events may legitimately have no public Root. They
  // belong in the execution ledger, never as a synthetic Post in the chat.
  if (!turnId || turnId === 'unscoped' || !turn) return null;
  const { activities, lanes, userMessageIds } = selectRoomTurnExecution(
    projection,
    turnId,
  );
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
  const kernelRootState = kernelRootsById?.[rootId]?.state;
  const rootBlocked = kernelRootState === 'blocked';
  const rootActive = !rootBlocked
    && (kernelRootState
      ? ['pending', 'running', 'waiting'].includes(kernelRootState)
      : ['queued', 'running'].includes(turn.status) && rootHasActiveLane)
    && !pendingAction;
  const rootStopping = abortingTurnIds.has(rootId);
  const rootRetrying = retryingRootIds.has(rootId);
  const terminalIssue = turn.status === 'failed' || turn.status === 'aborted'
    ? turn.status
    : '';
  const publicFailure = publicAgentErrorText(
    turn.failure,
    '伙伴未能完成这轮任务，你可以调整原消息后再试。',
  );
  const outcome = roomTurnOutcome(projection, lanes, turn, publicFailure);
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
    {userMessageIds.map((id) => {
      const message = projection.messagesById[id];
      if (!message) return null;
      return <div key={id} className="room-user-message" data-status={message.status}>
        <MarkdownBody text={message.text} />
        {message.status === 'queued' ? <small>正在发送</small> : null}
      </div>;
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
        .filter(Boolean);
      const visibleMessages = roomVisibleLaneMessages(messages);
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
      const laneOutcome = visibleMessages.reduce((outcome, message) => (
        roomTerminalPostLabels[message.postKind ?? '']
          ? message.postKind ?? outcome
          : outcome
      ), '');
      const laneComplete = (laneTerminal || Boolean(laneOutcome)) && !laneFailed && !laneAborted;
      const statusLabel = laneAction
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
      const sessionId = lane.sourceSessionId || participant?.sessionId || '';
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
      return <section className="room-agent-lane" data-outcome={laneOutcome || undefined} data-state={laneState} key={lane.key}>
        <header>
          {participant
            ? <PersonaAvatar
                persona={persona}
                presence={laneState === 'running'
                  ? 'thinking'
                  : laneState === 'waiting'
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
          <RoomElapsed
            startedAtMs={turn.createdAtMs}
            endedAtMs={laneActive && !laneAction ? undefined : turn.updatedAtMs}
          />
        </header>
        {lane.activities.length ? <ActivityLog
          activities={lane.activities}
          active={laneActive && !laneAction}
          participantName={participant?.displayName}
          attention={laneState === 'failed' || laneState === 'aborted'}
        /> : null}
        {!lane.activities.length && laneActive && !messages.length ? <div className="room-agent-lane__waiting"><LoaderCircle className="ui-spin" size={14} /><span>{participant ? `${participant.displayName} 已接手，正在准备` : '消息已经送达，正在请合适的伙伴回应'}</span></div> : null}
        {visibleMessages.map((message) => (
          <RoomLanePost key={message.id} message={message} />
        ))}
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
        <small className="room-turn__terminal-label">协作结果</small>
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
    if (candidate && ['running', 'waiting', 'failed'].includes(
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
  attention,
  participantName,
}: {
  activities: RoomActivityProjection[];
  active: boolean;
  attention: boolean;
  participantName?: string;
}) {
  const [open, setOpen] = useState(active || attention);
  const previousActive = useRef(active);
  useEffect(() => {
    const wasActive = previousActive.current;
    previousActive.current = active;
    if (active && !wasActive) {
      setOpen(true);
    } else if (!active && wasActive) {
      setOpen(attention);
    } else if (attention) {
      setOpen(true);
    }
  }, [active, attention]);
  const digest = roomActivityDigest(activities);
  return <details
    className="room-agent-lane__activity"
    data-state={active ? 'running' : attention ? 'attention' : 'settled'}
    open={open}
  >
    <summary
      aria-expanded={open}
      onClick={(event) => toggleDisclosurePreservingAnchor(event, setOpen)}
    >
      <Wrench size={14} />
      <span>
        <strong>{digest.title}</strong>
        <small>{digest.detail}</small>
      </span>
      <ChevronRight aria-hidden="true" size={14} />
    </summary>
    <div>{activities.map((activity) => {
      const displayStatus = roomActivityDisplayStatus(activity);
      const description = describeRoomActivity(activity, participantName);
      const sourceEventType = textValue(activity.payload.sourceEventType);
      if (['tool_started', 'tool_progress', 'tool_finished'].includes(sourceEventType)) {
        return <RoomToolActivity activity={activity} key={activity.id} />;
      }
      return <div className="room-agent-activity" data-state={displayStatus} key={activity.id}>
        {displayStatus === 'running'
          ? <LoaderCircle className="ui-spin" size={14} />
          : displayStatus === 'failed'
            ? <X size={14} />
            : displayStatus === 'waiting'
              ? <Clock3 size={14} />
              : <CheckCircle2 size={14} />}
        <span><strong>{description.title}</strong><small>{description.detail}</small></span>
      </div>;
    })}</div>
  </details>;
}

function RoomLanePost({ message }: { message: RoomMessageProjection }) {
  const [open, setOpen] = useState(false);
  const visibleBlocks = roomVisibleBlocks(message.message?.blocks ?? []);
  const reportLabel = roomPostReportLabel(message);
  const collapsible = roomPostShouldCollapse(message, visibleBlocks);
  const content = visibleBlocks.length
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
    {message.status === 'streaming' ? <span className="room-stream-caret" aria-label="仍在生成" /> : null}
  </div>;
}

function roomPostShouldCollapse(
  message: RoomMessageProjection,
  blocks: NonNullable<RoomMessageProjection['message']>['blocks'],
): boolean {
  if (message.projectionKind === 'execution' || message.status === 'streaming') return false;
  if (blocks.some((block) => !['text', 'progress', 'status'].includes(block.type))) return false;
  const normalized = message.text.replace(/\s+/g, ' ').trim();
  return normalized.length > 360 || message.text.split('\n').length > 8;
}

function roomReportPreview(value: string): string {
  const normalized = value
    .replace(/```[\s\S]*?```/g, '（含代码或命令回执）')
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
    const visibleMessages = roomVisibleLaneMessages(
      lane.messageIds
        .map((id) => projection.messagesById[id])
        .filter(Boolean),
    );
    const terminalPosts = visibleMessages.filter((message) => (
      message.projectionKind !== 'execution'
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

function roomActivityDigest(
  activities: RoomActivityProjection[],
): { title: string; detail: string } {
  const labels = activities.flatMap((activity) => {
    const sourceEventType = textValue(activity.payload.sourceEventType);
    if (sourceEventType.startsWith('tool_')) {
      const toolId = textValue(activity.payload.toolName);
      return [publicToolName(toolId, textValue(activity.payload.displayName))];
    }
    if (sourceEventType === 'reasoning_summary') return ['思路更新'];
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
  }, { running: 0, waiting: 0, failed: 0, completed: 0 });
  const states = [
    counts.running ? `${counts.running} 个进行中` : '',
    counts.waiting ? `${counts.waiting} 个等待处理` : '',
    counts.failed ? `${counts.failed} 个未完成` : '',
    !counts.running && !counts.waiting && !counts.failed
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


function RoomToolActivity({ activity }: { activity: RoomActivityProjection }) {
  const [open, setOpen] = useState(false);
  const payload = activity.payload;
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
  return (
    <details
      className="room-agent-activity room-agent-activity--tool"
      data-state={activity.status}
      open={open}
    >
      <summary
        aria-expanded={open}
        onClick={(event) => toggleDisclosurePreservingAnchor(event, setOpen)}
      >
        <span className="room-agent-activity__state" aria-hidden="true">
          {activity.status === 'running'
            ? <LoaderCircle className="ui-spin" size={14} />
            : activity.status === 'failed'
              ? <X size={14} />
              : <CheckCircle2 size={14} />}
        </span>
        <span>
          <strong>{activity.status === 'failed' ? `${detailView.toolLabel}执行失败` : detailView.summary}</strong>
          <small>{detailView.toolLabel} · {roomToolStatusLabel(activity.status)}{roomToolProgressCount(payload) > 1 ? ` · ${roomToolProgressCount(payload)} 次更新` : ''}</small>
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
          {activity.status === 'running' && safeResult === undefined ? (
            <p className="room-agent-activity__unavailable">工具尚未返回结果。</p>
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
  deduplicated: ['新回执', '已去重'],
  currentResponsibilityContinues: ['职责已移交', '继续当前职责'],
  ok: ['未成功', '成功'],
  created: ['已有回执', '新回执'],
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
  return '已返回';
}

function roomToolProgressCount(payload: Record<string, unknown>): number {
  return Array.isArray(payload.progressHistory) ? payload.progressHistory.length : 0;
}

function RoomElapsed({ startedAtMs, endedAtMs }: { startedAtMs: number; endedAtMs?: number }) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (endedAtMs != null) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [endedAtMs]);
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
      title: summary || `${participantName} 正在梳理下一步`,
      detail: activity.status === 'running' ? '公开思路仍在更新' : '公开思路已同步',
    };
  }
  if (['current_progress', 'progress'].includes(sourceEventType)) {
    const summary = publicActivitySummary(activity.summary, activity.kind);
    return {
      title: summary || `${participantName} 正在推进任务`,
      detail: activity.status === 'running' ? '当前工作进度' : '工作进度已同步',
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
