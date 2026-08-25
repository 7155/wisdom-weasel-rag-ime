import {
  roomActivityLaneIdentity,
  roomExecutionLaneKey,
  type RoomActivityProjection,
  type RoomMessageProjection,
  type RoomProjectionState,
} from '@/contracts/room-reducer';
import { approvalNeedsHumanDecision } from '@/contracts/approval-decision';

export interface RoomExecutionLane {
  key: string;
  rootId: string;
  dispatchId: string;
  sourceTurnId: string;
  sourceLoopId: string;
  waveId: string;
  phaseName: string;
  parallelIndex?: number;
  parallelSize?: number;
  participantId: string | null;
  sourceSessionId: string;
  activities: RoomActivityProjection[];
  messageIds: string[];
}

export interface RoomTurnExecution {
  activities: RoomActivityProjection[];
  lanes: RoomExecutionLane[];
  messageIds: string[];
  userMessageIds: string[];
}

export interface RoomExecutionOverviewItem {
  id: string;
  objective: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'aborted';
  participantIds: string[];
  sessionIds: string[];
  laneCount: number;
  toolCount: number;
  lastSummary: string;
  updatedAtMs: number;
}

/** Keep Room/session lifecycle records out of the virtualized public timeline. */
export function selectPublicRoomTurnOrder(
  projection: RoomProjectionState,
): string[] {
  const successorByRoot = new Map<string, string>();
  const retryChildren = new Set<string>();
  for (const turnId of projection.turnOrder) {
    const retryOfRootId = projection.turnsById[turnId]?.retryOfRootId;
    if (!retryOfRootId || !projection.turnsById[retryOfRootId]) continue;
    successorByRoot.set(retryOfRootId, turnId);
    retryChildren.add(turnId);
  }
  return projection.turnOrder.flatMap((turnId) => {
    if (
      turnId === 'unscoped'
      || retryChildren.has(turnId)
      || isDetachedIntercomTurn(projection, turnId)
    ) return [];
    let leaf = turnId;
    const visited = new Set<string>([leaf]);
    while (successorByRoot.has(leaf)) {
      const next = successorByRoot.get(leaf)!;
      if (visited.has(next)) break;
      visited.add(next);
      leaf = next;
    }
    return [leaf];
  });
}

/**
 * The newest logical public root is the only root allowed to keep the Room
 * composer in steering mode. A historical root can remain locally incomplete
 * after reconnect/history hydration, but it must not override a newer
 * terminal root.
 */
export function selectActivePublicRoomTurn(projection: RoomProjectionState) {
  const latestTurnId = selectPublicRoomTurnOrder(projection).at(-1);
  if (!latestTurnId) return undefined;
  const latestTurn = projection.turnsById[latestTurnId];
  return latestTurn?.status === 'queued' || latestTurn?.status === 'running'
    ? latestTurn
    : undefined;
}

/**
 * Intercom receipts are Room-wide relationship facts, not independent public
 * conversation turns. Their delivery turn ids belong to the receiving Pi
 * Session and do not receive a matching Room `turn_completed` event. Leaving
 * them in the public order therefore makes a delivered message look like a
 * permanently running Room turn.
 */
function isDetachedIntercomTurn(
  projection: RoomProjectionState,
  turnId: string,
): boolean {
  const turn = projection.turnsById[turnId];
  if (!turn || turn.messageIds.length > 0 || turn.activityIds.length === 0) return false;
  return turn.activityIds.every((activityId) => {
    const activity = projection.activitiesById[activityId];
    return activity?.kind === 'participant_activity'
      && textValue(activity.payload.activityKind) === 'intercom';
  });
}

/** Project real Pi Session dispatches into the Room task view.
 *
 * Explicit WorkItems are optional in the light Room architecture. The task
 * view must therefore derive its primary state from the same Room event
 * projection as the conversation timeline instead of presenting an active
 * collaboration as empty.
 */
export function selectRoomExecutionOverview(
  projection: RoomProjectionState,
  limit = 8,
): RoomExecutionOverviewItem[] {
  return selectPublicRoomTurnOrder(projection)
    .slice(-Math.max(1, limit))
    .reverse()
    .flatMap((turnId) => {
      const turn = projection.turnsById[turnId];
      if (!turn) return [];
      const execution = selectRoomTurnExecution(projection, turnId);
      const userMessages = execution.userMessageIds
        .map((messageId) => projection.messagesById[messageId])
        .filter((message): message is RoomMessageProjection => Boolean(message));
      const objective = [...userMessages]
        .reverse()
        .map((message) => message.text.trim())
        .find(Boolean) ?? '继续当前协作';
      const participantIds = [...new Set(execution.lanes
        .map((lane) => lane.participantId)
        .filter((participantId): participantId is string => Boolean(participantId)))];
      const sessionIds = [...new Set(execution.lanes
        .map((lane) => lane.sourceSessionId.trim())
        .filter(Boolean))];
      const toolActivities = execution.activities.filter((activity) => {
        const sourceEventType = textValue(activity.payload.sourceEventType);
        return activity.kind === 'tool' || sourceEventType.startsWith('tool_');
      });
      const lastSummary = [...execution.activities]
        .reverse()
        .map((activity) => activity.summary.trim())
        .find(Boolean) ?? '';
      return [{
        id: turnId,
        objective,
        status: turn.status,
        participantIds,
        sessionIds,
        laneCount: execution.lanes.length,
        toolCount: toolActivities.length,
        lastSummary,
        updatedAtMs: turn.updatedAtMs,
      }];
    });
}

/** Build stable root + participant + dispatch slots for one public Room turn. */
export function selectRoomTurnExecution(
  projection: RoomProjectionState,
  turnId: string,
): RoomTurnExecution {
  const turn = projection.turnsById[turnId];
  if (!turn) return { activities: [], lanes: [], messageIds: [], userMessageIds: [] };

  const activities = turn.activityIds
    .map((id) => projection.activitiesById[id])
    .filter((activity): activity is RoomActivityProjection => Boolean(activity))
    .filter(isUsefulRoomActivity);
  const lanes = new Map<string, RoomExecutionLane>();
  const participantLaneKeys = new Map<string, string[]>();

  for (const activity of activities) {
    const identity = roomActivityLaneIdentity(activity);
    const participantId = textValue(activity.payload.targetParticipantId)
      || activity.participantId
      || null;
    const lane = lanes.get(identity.key) ?? {
      key: identity.key,
      rootId: identity.rootId,
      dispatchId: identity.dispatchId,
      sourceTurnId: identity.sourceTurnId,
      sourceLoopId: identity.sourceLoopId,
      waveId: textValue(activity.payload.waveId),
      phaseName: textValue(activity.payload.phaseName),
      parallelIndex: numberValue(activity.payload.parallelIndex),
      parallelSize: numberValue(activity.payload.parallelSize),
      participantId,
      sourceSessionId: activity.sourceSessionId,
      activities: [],
      messageIds: [],
    };
    lane.activities.push(activity);
    lane.waveId ||= textValue(activity.payload.waveId);
    lane.phaseName ||= textValue(activity.payload.phaseName);
    lane.parallelIndex ??= numberValue(activity.payload.parallelIndex);
    lane.parallelSize ??= numberValue(activity.payload.parallelSize);
    if (!lane.participantId && participantId) lane.participantId = participantId;
    if (!lane.sourceSessionId && activity.sourceSessionId) {
      lane.sourceSessionId = activity.sourceSessionId;
    }
    lanes.set(identity.key, lane);
    appendLaneKey(
      participantLaneKeys,
      participantKey(participantId, activity.sourceSessionId),
      identity.key,
    );
  }

  const messageIds: string[] = [];
  for (const messageId of turn.messageIds) {
    const message = projection.messagesById[messageId];
    if (!message) continue;
    messageIds.push(messageId);
    if (message.role === 'user') {
      continue;
    }
    const messageRootId = message.rootId || turn.rootId || turnId;
    const messageParticipantId = message.participantId
      || message.sourceSessionId
      || 'participant';
    const messageLoopId = message.sourceLoopId || message.sourceTurnId || '';
    const exactKey = message.dispatchId && messageLoopId
      ? roomExecutionLaneKey(
          messageRootId,
          messageParticipantId,
          message.dispatchId,
          messageLoopId,
        )
      : '';
    const existingKey = exactKey && lanes.has(exactKey)
      ? exactKey
      : matchingParticipantLaneKey(
          lanes,
          participantLaneKeys,
          projection,
          message,
        );
    const laneKey = existingKey ?? roomExecutionLaneKey(
      messageRootId,
      messageParticipantId,
      message.dispatchId || message.id,
      messageLoopId,
    );
    const lane = lanes.get(laneKey) ?? {
      key: laneKey,
      rootId: messageRootId,
      dispatchId: message.dispatchId || '',
      sourceTurnId: message.sourceTurnId || '',
      sourceLoopId: message.sourceLoopId || '',
      waveId: '',
      phaseName: '',
      participantId: message.participantId,
      sourceSessionId: message.sourceSessionId,
      activities: [],
      messageIds: [],
    };
    if (!lane.messageIds.includes(messageId)) lane.messageIds.push(messageId);
    lanes.set(laneKey, lane);
  }

  if (lanes.size === 0 && ['queued', 'running'].includes(turn.status)) {
    lanes.set(`${turnId}\u001frouter\u001fpending`, {
      key: `${turnId}\u001frouter\u001fpending`,
      rootId: turn.rootId || turnId,
      dispatchId: '',
      sourceTurnId: '',
      sourceLoopId: '',
      waveId: '',
      phaseName: '',
      participantId: null,
      sourceSessionId: '',
      activities: [],
      messageIds: [],
    });
  }
  const originalMessageIndexById = new Map(
    turn.messageIds.map((messageId, index) => [messageId, index]),
  );
  const orderedMessageIds = messageIds.sort((leftId, rightId) => (
    compareRoomMessages(
      projection.messagesById[leftId]!,
      projection.messagesById[rightId]!,
      originalMessageIndexById.get(leftId) ?? Number.MAX_SAFE_INTEGER,
      originalMessageIndexById.get(rightId) ?? Number.MAX_SAFE_INTEGER,
    )
  ));
  const visibleLanes = coalesceInternalAttemptLanes([...lanes.values()]);
  const laneIndex = new Map(visibleLanes.map((lane, index) => [lane.key, index]));
  visibleLanes.sort((left, right) => compareExecutionLanes(
    left,
    right,
    projection,
    laneIndex.get(left.key) ?? Number.MAX_SAFE_INTEGER,
    laneIndex.get(right.key) ?? Number.MAX_SAFE_INTEGER,
  ));
  return {
    activities,
    lanes: visibleLanes,
    messageIds: orderedMessageIds,
    userMessageIds: orderedMessageIds.filter((messageId) => (
      projection.messagesById[messageId]?.role === 'user'
    )),
  };
}

function matchingParticipantLaneKey(
  lanes: Map<string, RoomExecutionLane>,
  participantLaneKeys: Map<string, string[]>,
  projection: RoomProjectionState,
  message: RoomMessageProjection,
): string | undefined {
  const candidates = (
    participantLaneKeys.get(
      participantKey(message.participantId, message.sourceSessionId),
    ) ?? []
  )
    .map((key) => lanes.get(key))
    .filter((lane): lane is RoomExecutionLane => Boolean(lane))
    .filter((lane) => !message.dispatchId || lane.dispatchId === message.dispatchId);
  if (candidates.length === 0) return undefined;

  const messageSequence = message.chronology?.roomEventSequence ?? message.sequence;
  if (messageSequence !== undefined) {
    const earlier = candidates.filter(
      (lane) => laneEarliestSequence(lane, projection) <= messageSequence,
    );
    if (earlier.length > 0) {
      return earlier.reduce((latest, candidate) => (
        laneEarliestSequence(candidate, projection)
          >= laneEarliestSequence(latest, projection)
          ? candidate
          : latest
      )).key;
    }
  }

  const earlierByTime = candidates.filter(
    (lane) => laneEarliestAtMs(lane, projection) <= message.createdAtMs,
  );
  return (earlierByTime.at(-1) ?? candidates.at(-1))?.key;
}

function compareExecutionLanes(
  left: RoomExecutionLane,
  right: RoomExecutionLane,
  projection: RoomProjectionState,
  leftIndex: number,
  rightIndex: number,
): number {
  const sequenceOrder = laneEarliestSequence(left, projection)
    - laneEarliestSequence(right, projection);
  if (Number.isFinite(sequenceOrder) && sequenceOrder !== 0) return sequenceOrder;
  const timeOrder = laneEarliestAtMs(left, projection)
    - laneEarliestAtMs(right, projection);
  if (Number.isFinite(timeOrder) && timeOrder !== 0) return timeOrder;
  return leftIndex - rightIndex || left.key.localeCompare(right.key);
}

function laneEarliestSequence(
  lane: RoomExecutionLane,
  projection: RoomProjectionState,
): number {
  return Math.min(
    ...lane.activities.map(
      (activity) => activity.sequence ?? Number.MAX_SAFE_INTEGER,
    ),
    ...lane.messageIds.map((messageId) => (
      projection.messagesById[messageId]?.chronology?.roomEventSequence
      ?? projection.messagesById[messageId]?.sequence
      ?? Number.MAX_SAFE_INTEGER
    )),
  );
}

function laneEarliestAtMs(
  lane: RoomExecutionLane,
  projection: RoomProjectionState,
): number {
  return Math.min(
    ...lane.activities.map((activity) => activity.createdAtMs),
    ...lane.messageIds.map((messageId) => (
      projection.messagesById[messageId]?.chronology?.createdAtMs
      ?? projection.messagesById[messageId]?.createdAtMs
      ?? Number.MAX_SAFE_INTEGER
    )),
  );
}

/**
 * Legacy events did not expose the Pi loop id. Preserve their old best-effort
 * coalescing, but every factual sourceLoopId is a visible loop and must remain
 * its own card even when it has no public Post yet. sourceTurnId remains a
 * compatibility fallback for already persisted Room events.
 */
function coalesceInternalAttemptLanes(
  source: RoomExecutionLane[],
): RoomExecutionLane[] {
  const indexesByParticipant = new Map<string, number[]>();
  source.forEach((lane, index) => {
    const key = participantKey(lane.participantId, lane.sourceSessionId);
    const indexes = indexesByParticipant.get(key) ?? [];
    indexes.push(index);
    indexesByParticipant.set(key, indexes);
  });
  const hidden = new Set<number>();
  for (const indexes of indexesByParticipant.values()) {
    let nextVisibleIndex: number | undefined;
    for (let offset = indexes.length - 1; offset >= 0; offset -= 1) {
      const index = indexes[offset]!;
      const lane = source[index]!;
      const isVisibleStep = Boolean(lane.sourceLoopId || lane.sourceTurnId)
        || Boolean(lane.waveId)
        || lane.messageIds.length > 0
        || nextVisibleIndex === undefined;
      if (isVisibleStep) {
        nextVisibleIndex = index;
        continue;
      }
      const targetIndex = nextVisibleIndex;
      if (targetIndex === undefined) continue;
      const target = source[targetIndex];
      if (!target) continue;
      target.activities = [...lane.activities, ...target.activities];
      hidden.add(index);
    }
  }
  return source.filter((_lane, index) => !hidden.has(index));
}

function compareRoomMessages(
  left: RoomMessageProjection,
  right: RoomMessageProjection,
  leftIndex: number,
  rightIndex: number,
): number {
  const leftSequence = left.chronology?.roomEventSequence ?? left.sequence;
  const rightSequence = right.chronology?.roomEventSequence ?? right.sequence;
  if (leftSequence !== undefined || rightSequence !== undefined) {
    if (leftSequence === undefined) return 1;
    if (rightSequence === undefined) return -1;
    const sequenceOrder = leftSequence - rightSequence;
    if (sequenceOrder !== 0) return sequenceOrder;
  }
  const timeOrder = (
    left.chronology?.createdAtMs ?? left.createdAtMs
  ) - (
    right.chronology?.createdAtMs ?? right.createdAtMs
  );
  if (timeOrder !== 0) return timeOrder;
  if (left.chronology?.afterPostId === right.id) return 1;
  if (right.chronology?.afterPostId === left.id) return -1;
  const orderKeyOrder = (left.chronology?.orderKey ?? '').localeCompare(
    right.chronology?.orderKey ?? '',
  );
  if (orderKeyOrder !== 0) return orderKeyOrder;
  const identityOrder = (
    left.sourceEventId
    || left.sourceMessageId
    || left.id
  ).localeCompare(
    right.sourceEventId
    || right.sourceMessageId
    || right.id,
  );
  return identityOrder || leftIndex - rightIndex;
}

/** Only explicit unresolved human requests pause a Room lane for Session action. */
export function roomActivityNeedsSessionAction(
  activity: RoomActivityProjection,
): boolean {
  const resolutionState = textValue(
    activity.payload.resolutionState || activity.payload.state,
  );
  if (
    ['approved', 'rejected', 'applied', 'resolved', 'cancelled'].includes(
      resolutionState,
    )
  ) return false;
  const requestKind = textValue(activity.payload.requestKind);
  return (Boolean(textValue(activity.payload.approvalId)) && approvalNeedsHumanDecision(activity.payload))
    || ['memory_review', 'plan_review', 'user_input_required', 'grouped_questions'].includes(
      requestKind,
    )
    || textValue(activity.payload.sourceEventType) === 'user_input_required'
    || (
      textValue(activity.payload.method) === 'select'
      && Array.isArray(activity.payload.options)
    );
}

function appendLaneKey(
  index: Map<string, string[]>,
  participant: string,
  laneKey: string,
): void {
  const keys = index.get(participant) ?? [];
  if (!keys.includes(laneKey)) keys.push(laneKey);
  index.set(participant, keys);
}

function participantKey(participantId: string | null, sessionId: string): string {
  return `${participantId ?? ''}\u001f${sessionId}`;
}

function isUsefulRoomActivity(activity: RoomActivityProjection): boolean {
  if (activity.kind !== 'participant_activity') return true;
  const sourceEventType = textValue(activity.payload.sourceEventType);
  if (
    ['tool_started', 'tool_progress', 'tool_finished'].includes(sourceEventType)
    && textValue(activity.payload.toolName).toLowerCase() === 'todo'
  ) return false;
  if (
    activity.status === 'failed'
    || activity.payload.isError === true
    || textValue(activity.payload.status) === 'provider_error'
  ) return true;
  if (['tool_started', 'tool_progress', 'tool_finished'].includes(sourceEventType)) {
    return true;
  }
  if (['reasoning_summary', 'current_progress', 'progress'].includes(sourceEventType)) {
    return true;
  }
  if (['child', 'intercom', 'work'].includes(textValue(activity.payload.activityKind))) return true;
  const requestKind = textValue(activity.payload.requestKind);
  if (
    activity.status === 'waiting'
    || ['memory_review', 'plan_review', 'user_input_required', 'grouped_questions'].includes(requestKind)
    || sourceEventType === 'user_input_required'
    || (
      textValue(activity.payload.method) === 'select'
      && Array.isArray(activity.payload.options)
    )
  ) return true;
  return Boolean(textValue(activity.payload.approvalId));
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function numberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}
