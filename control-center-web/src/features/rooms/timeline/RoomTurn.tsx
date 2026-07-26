import {
  CheckCircle2,
  CircleStop,
  Clock3,
  ExternalLink,
  LoaderCircle,
  Route,
  Wrench,
  X,
} from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/primitives';
import {
  type RoomActivityProjection,
  type RoomProjectionState,
} from '@/contracts/room-reducer';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { AgentBlocks, MarkdownBody } from '@/features/agent/timeline/BlockRenderer';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { selectRoomTurnExecution } from '../runtime/room-execution-lanes';
import { roomProjection, useRoomLiveStore } from '../state/live-store';

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
  abortingSessionIds?: ReadonlySet<string>;
  abortingTurnIds?: ReadonlySet<string>;
  onAbortTurn?: (rootId: string) => void;
  onAbortSession?: (sessionId: string) => void;
}

/** Render one Root as independent participant/dispatch execution lanes. */
export function RoomTurn({
  turnId,
  roomId = '',
  room,
  projection: providedProjection,
  personas,
  abortingSessionIds = new Set(),
  abortingTurnIds = new Set(),
  onAbortTurn,
  onAbortSession,
}: RoomTurnProps) {
  useRoomLiveStore((state) => (
    providedProjection ? 0 : state.turnRevisions[roomId]?.[turnId] ?? 0
  ));
  const projection = providedProjection ?? roomProjection(roomId);
  const turn = projection.turnsById[turnId];
  // Room/session lifecycle events may legitimately have no public Root. They
  // belong in the execution ledger, never as a synthetic Post in the chat.
  if (!turnId || turnId === 'unscoped' || !turn) return null;
  const { activities, lanes, userMessageIds } = selectRoomTurnExecution(
    projection,
    turnId,
  );
  const reviewActivity = [...activities].reverse().find((activity) => {
    const requestKind = textValue(activity.payload.requestKind);
    const approvalId = textValue(activity.payload.approvalId);
    const state = textValue(activity.payload.state);
    return requestKind === 'memory_review'
      || Boolean(approvalId && !['approved', 'rejected', 'applied'].includes(state));
  });
  const reviewSessionId = reviewActivity?.sourceSessionId
    || room?.participants.find((item) => item.id === reviewActivity?.participantId)?.sessionId
    || '';
  const rootId = turn.rootId || turnId;
  const rootActive = (rootId.startsWith('room-turn:') || rootId.startsWith('room-root:'))
    && ['queued', 'running'].includes(turn.status);
  const rootStopping = abortingTurnIds.has(rootId);
  return <article className="room-turn">
    {userMessageIds.map((id) => {
      const message = projection.messagesById[id];
      if (!message) return null;
      return <div key={id} className="room-user-message" data-status={message.status}>
        <MarkdownBody text={message.text} />
        {message.status === 'queued' ? <small>正在发送</small> : null}
      </div>;
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
    {lanes.map((lane) => {
      const participant = room?.participants.find((item) => item.id === lane.participantId);
      const persona = personas.find((item) => (
        item.roleId === participant?.roleId && item.version === participant.roleVersion
      ));
      const messages = lane.messageIds
        .map((id) => projection.messagesById[id])
        .filter(Boolean);
      const participantId = lane.participantId ?? '';
      const laneFailed = lane.dispatchId
        ? (turn.failedDispatchIds ?? []).includes(lane.dispatchId)
        : participantId
          ? (turn.failedParticipantIds ?? []).includes(participantId)
          : turn.status === 'failed';
      const laneAborted = lane.dispatchId
        ? (turn.abortedDispatchIds ?? []).includes(lane.dispatchId)
        : participantId
          ? (turn.abortedParticipantIds ?? []).includes(participantId)
          : turn.status === 'aborted';
      const laneTerminal = lane.dispatchId
        ? (turn.terminalDispatchIds ?? []).includes(lane.dispatchId)
        : participantId
          ? (turn.terminalParticipantIds ?? []).includes(participantId)
          : ['completed', 'failed', 'aborted'].includes(turn.status);
      const laneActive = !laneTerminal && !laneFailed && !laneAborted;
      const laneComplete = laneTerminal && !laneFailed && !laneAborted
        && messages.every((message) => message.status === 'completed');
      const statusLabel = laneFailed
        ? '未完成'
        : laneComplete
          ? '已完成'
          : laneAborted
            ? '已停止'
            : participant
              ? '执行中'
              : '正在发送';
      const sessionId = lane.sourceSessionId || participant?.sessionId || '';
      const stopping = abortingSessionIds.has(sessionId);
      const laneState = laneFailed
        ? 'failed'
        : laneAborted
          ? 'aborted'
          : laneActive
            ? 'running'
            : 'completed';
      return <section className="room-agent-lane" data-state={laneState} key={lane.key}>
        <header>
          {participant
            ? <PersonaAvatar persona={persona} presence={laneActive ? 'thinking' : 'done'} />
            : <span className="room-agent-lane__route"><Route size={15} /></span>}
          <span className="room-agent-lane__identity">
            <strong>{participant?.displayName ?? '正在选择伙伴'}</strong>
            <small>{statusLabel}</small>
          </span>
          <RoomElapsed
            startedAtMs={turn.createdAtMs}
            endedAtMs={laneActive ? undefined : turn.updatedAtMs}
          />
          {laneActive && sessionId && onAbortSession ? <Button
            variant="quiet"
            size="small"
            leadingIcon={stopping ? <LoaderCircle className="ui-spin" size={14} /> : <CircleStop size={14} />}
            disabled={stopping}
            onClick={() => onAbortSession(sessionId)}
          >{stopping ? '正在停止' : '停止这位伙伴'}</Button> : null}
        </header>
        {lane.activities.length ? <ActivityLog
          activities={lane.activities}
          active={laneActive}
          participantName={participant?.displayName}
        /> : null}
        {!lane.activities.length && laneActive && !messages.length ? <div className="room-agent-lane__waiting"><LoaderCircle className="ui-spin" size={14} /><span>{participant ? `${participant.displayName} 已接手，正在准备` : '消息已经送达，正在请合适的伙伴回应'}</span></div> : null}
        {messages.map((message) => {
          const visibleBlocks = message.message?.blocks.filter((block) => (
            block.type !== 'reasoning_summary'
            && block.type !== 'tool_call'
            && block.type !== 'tool_result'
            && block.visibility !== 'private_session'
          ));
          const needsReview = visibleBlocks?.some((block) => (
            block.type === 'approval'
            && !['approved', 'rejected', 'applied'].includes(textValue(block.data.state))
          ));
          return <div
            className="room-agent-lane__post"
            data-projection={message.projectionKind ?? 'post'}
            data-status={message.status}
            key={message.id}
          >
            {message.projectionKind === 'execution' ? <small className="room-agent-lane__projection-label">实时进展 · 完成后会在这里留下公开结果</small> : null}
            {visibleBlocks?.length
              ? <AgentBlocks blocks={visibleBlocks} sessionId={message.message?.sessionId ?? message.sourceSessionId} />
              : message.text
                ? <MarkdownBody text={message.text} />
                : null}
            {message.status === 'streaming' ? <span className="room-stream-caret" aria-label="仍在生成" /> : null}
            {needsReview && sessionId ? <ReviewLink sessionId={sessionId} /> : null}
          </div>;
        })}
        {laneFailed && !messages.length ? <p className="room-agent-lane__failure">{turn.failure || '这轮协作没有完成，可以调整后重试。'}</p> : null}
      </section>;
    })}
    {reviewSessionId ? <ReviewLink sessionId={reviewSessionId} wholeTurn /> : null}
  </article>;
}

function ReviewLink({ sessionId, wholeTurn = false }: { sessionId: string; wholeTurn?: boolean }) {
  return <a
    className={`room-review-link${wholeTurn ? ' room-review-link--turn' : ''}`}
    href={agentSessionHref(sessionId)}
  >
    <span>
      <strong>{wholeTurn ? '这轮协作正在等待审阅' : '需要在伙伴对话中审阅'}</strong>
      <small>{wholeTurn ? '伙伴已暂停；打开对应对话处理后会自动继续。' : '打开对应伙伴，批准或拒绝这项操作。'}</small>
    </span>
    <span>{wholeTurn ? '立即审阅' : '前往审阅'} <ExternalLink size={13} /></span>
  </a>;
}

function ActivityLog({
  activities,
  active,
  participantName,
}: {
  activities: RoomActivityProjection[];
  active: boolean;
  participantName?: string;
}) {
  const [open, setOpen] = useState(active);
  return <details
    className="room-agent-lane__activity"
    open={open}
    onToggle={(event) => setOpen(event.currentTarget.open)}
  >
    <summary><Wrench size={14} /><span>{active ? '正在处理' : '过程记录'}</span><small>{activities.length} 项</small></summary>
    <div>{activities.map((activity) => {
      const displayStatus = roomActivityDisplayStatus(activity);
      const description = describeRoomActivity(activity, participantName);
      return <div className="room-agent-activity" data-state={displayStatus} key={activity.id}>
        {displayStatus === 'running'
          ? <LoaderCircle className="ui-spin" size={14} />
          : displayStatus === 'failed'
            ? <X size={14} />
            : <CheckCircle2 size={14} />}
        <span><strong>{description.title}</strong><small>{description.detail}</small></span>
      </div>;
    })}</div>
  </details>;
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
  if (activity.status === 'running') return { title: `${participantName} 正在处理`, detail: '有新进展时会在这里更新' };
  return { title: `${participantName} 完成了一步`, detail: '协作进度已经同步' };
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
