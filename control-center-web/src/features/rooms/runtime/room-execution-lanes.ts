import {
  roomActivityLaneIdentity,
  type RoomActivityProjection,
  type RoomMessageProjection,
  type RoomProjectionState,
} from '@/contracts/room-reducer';
import { approvalNeedsHumanDecision } from '@/contracts/approval-decision';

export interface RoomExecutionLane {
  key: string;
  rootId: string;
  executionPhase: number;
  taskId: string;
  dispatchId: string;
  dispatchIds: string[];
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

/** Keep Room/session lifecycle records out of the virtualized public timeline. */
export function selectPublicRoomTurnOrder(
  projection: RoomProjectionState,
): string[] {
  const originalIndex = new Map(
    projection.turnOrder.map((turnId, index) => [turnId, index]),
  );
  return projection.turnOrder
    .filter((turnId) => turnId !== 'unscoped')
    .sort((leftId, rightId) => {
      const createdOrder = (
        projection.turnsById[leftId]?.createdAtMs ?? Number.MAX_SAFE_INTEGER
      ) - (
        projection.turnsById[rightId]?.createdAtMs ?? Number.MAX_SAFE_INTEGER
      );
      return createdOrder
        || (originalIndex.get(leftId) ?? Number.MAX_SAFE_INTEGER)
          - (originalIndex.get(rightId) ?? Number.MAX_SAFE_INTEGER)
        || leftId.localeCompare(rightId);
    });
}

/** Build stable root + participant + dispatch slots for one public Room turn. */
export function selectRoomTurnExecution(
  projection: RoomProjectionState,
  turnId: string,
  taskIdByDispatchId: Readonly<Record<string, string>> = {},
): RoomTurnExecution {
  const turn = projection.turnsById[turnId];
  if (!turn) return { activities: [], lanes: [], messageIds: [], userMessageIds: [] };

  const activities = turn.activityIds
    .map((id) => projection.activitiesById[id])
    .filter((activity): activity is RoomActivityProjection => Boolean(activity))
    .filter(isUsefulRoomActivity);
  const executionPhaseBoundaries = turn.messageIds
    .map((messageId) => projection.messagesById[messageId])
    .filter((message): message is RoomMessageProjection => Boolean(message))
    .filter(isRoomExecutionStartMessage)
    .map((message) => ({
      sequence: message.chronology?.roomEventSequence ?? message.sequence,
      createdAtMs: message.chronology?.createdAtMs ?? message.createdAtMs,
    }));
  const lanes = new Map<string, RoomExecutionLane>();
  const participantLaneKeys = new Map<string, string[]>();
  const dispatchLaneKeys = new Map<string, string>();

  for (const activity of activities) {
    const sourceIdentity = roomActivityLaneIdentity(activity);
    const taskId = sourceIdentity.taskId
      || taskIdByDispatchId[sourceIdentity.dispatchId]
      || '';
    const identity = { ...sourceIdentity, taskId };
    const participantId = activity.participantId
      || textValue(activity.payload.targetParticipantId)
      || null;
    const participantIdentity = participantKey(participantId, activity.sourceSessionId);
    const executionPhase = roomExecutionPhaseOrdinal(
      activity.sequence,
      activity.updatedAtMs ?? activity.createdAtMs,
      executionPhaseBoundaries,
    );
    // Work-item lifecycle updates may omit Dispatch/Task ids even though they
    // belong to the same participant Session. Keep them in the existing role
    // card instead of introducing a second avatar/card for one assignment.
    const hasAuthoritativeWorkIdentity = Boolean(
      textValue(activity.payload.taskId) || textValue(activity.payload.dispatchId),
    );
    const existingParticipantLane = !hasAuthoritativeWorkIdentity
      ? participantLaneKeys.get(participantIdentity)?.at(-1)
      : undefined;
    const canonicalTaskLane = identity.taskId
      ? taskLaneKey(identity.rootId, participantId, identity.taskId, executionPhase)
      : '';
    const laneKey = existingParticipantLane || canonicalTaskLane || identity.key;
    const lane = lanes.get(laneKey) ?? {
      key: laneKey,
      rootId: identity.rootId,
      executionPhase,
      taskId: identity.taskId,
      dispatchId: identity.dispatchId,
      dispatchIds: [],
      participantId,
      sourceSessionId: activity.sourceSessionId,
      activities: [],
      messageIds: [],
    };
    lane.activities.push(activity);
    if (identity.taskId) lane.taskId = identity.taskId;
    const authoritativeDispatchId = textValue(activity.payload.dispatchId);
    if (authoritativeDispatchId) {
      lane.dispatchId = authoritativeDispatchId;
      if (!lane.dispatchIds.includes(authoritativeDispatchId)) {
        lane.dispatchIds.push(authoritativeDispatchId);
      }
      dispatchLaneKeys.set(authoritativeDispatchId, laneKey);
    }
    if (activity.sourceSessionId) lane.sourceSessionId = activity.sourceSessionId;
    if (!lane.participantId && participantId) lane.participantId = participantId;
    if (!lane.sourceSessionId && activity.sourceSessionId) {
      lane.sourceSessionId = activity.sourceSessionId;
    }
    lanes.set(laneKey, lane);
    appendLaneKey(
      participantLaneKeys,
      participantIdentity,
      laneKey,
    );
  }

  const messageIds: string[] = [];
  for (const messageId of turn.messageIds) {
    const message = projection.messagesById[messageId];
    if (!message) continue;
    messageIds.push(messageId);
    if (message.role === 'user' && message.answerToPostId) {
      const answerLane = [...lanes.values()].find((candidate) => (
        candidate.messageIds.includes(message.answerToPostId ?? '')
      ));
      if (answerLane && !answerLane.messageIds.includes(messageId)) {
        answerLane.messageIds.push(messageId);
      }
      continue;
    }
    if (message.role === 'user') {
      continue;
    }
    const dispatchKey = message.dispatchId
      ? dispatchLaneKeys.get(message.dispatchId) ?? ''
      : '';
    const messageTaskId = message.dispatchId
      ? taskIdByDispatchId[message.dispatchId] ?? ''
      : '';
    const executionPhase = roomExecutionPhaseOrdinal(
      message.chronology?.roomEventSequence ?? message.sequence,
      message.chronology?.createdAtMs ?? message.createdAtMs,
      executionPhaseBoundaries,
    );
    const canonicalTaskLane = messageTaskId
      ? taskLaneKey(
          message.rootId || turn.rootId || turnId,
          message.participantId,
          messageTaskId,
          executionPhase,
        )
      : '';
    const exactKey = message.dispatchId
      ? [
          message.rootId || turn.rootId || turnId,
          message.participantId || message.sourceSessionId || 'participant',
          message.dispatchId,
        ].join('\u001f')
      : '';
    const existingKey = dispatchKey
      || (canonicalTaskLane && lanes.has(canonicalTaskLane) ? canonicalTaskLane : '')
      || (exactKey && lanes.has(exactKey)
      ? exactKey
      : !canonicalTaskLane ? participantLaneKeys
          .get(participantKey(message.participantId, message.sourceSessionId))
          ?.at(-1) : undefined);
    const laneKey = existingKey || canonicalTaskLane || [
      turn.rootId || turnId,
      message.participantId || message.sourceSessionId || 'participant',
      message.dispatchId || message.id,
    ].join('\u001f');
    const lane = lanes.get(laneKey) ?? {
      key: laneKey,
      rootId: message.rootId || turn.rootId || turnId,
      executionPhase,
      taskId: messageTaskId,
      dispatchId: message.dispatchId || '',
      dispatchIds: message.dispatchId ? [message.dispatchId] : [],
      participantId: message.participantId,
      sourceSessionId: message.sourceSessionId,
      activities: [],
      messageIds: [],
    };
    if (messageTaskId) lane.taskId = messageTaskId;
    if (message.dispatchId) {
      lane.dispatchId = message.dispatchId;
      if (!lane.dispatchIds.includes(message.dispatchId)) {
        lane.dispatchIds.push(message.dispatchId);
      }
      dispatchLaneKeys.set(message.dispatchId, laneKey);
    }
    if (!lane.messageIds.includes(messageId)) lane.messageIds.push(messageId);
    lanes.set(laneKey, lane);
    appendLaneKey(
      participantLaneKeys,
      participantKey(message.participantId, message.sourceSessionId),
      laneKey,
    );
  }

  if (lanes.size === 0 && ['queued', 'running'].includes(turn.status)) {
    lanes.set(`${turnId}\u001frouter\u001fpending`, {
      key: `${turnId}\u001frouter\u001fpending`,
      rootId: turn.rootId || turnId,
      executionPhase: executionPhaseBoundaries.length,
      taskId: '',
      dispatchId: '',
      dispatchIds: [],
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
  // Activities are grouped before posts, so the message pass must not make an
  // older attempt authoritative merely because it ran second. Resolve the
  // current Dispatch from the canonical cross-message event chronology after
  // every lane has been assembled.
  for (const lane of lanes.values()) {
    const latestDispatch = [
      ...lane.activities.map((activity, index) => ({
        dispatchId: textValue(activity.payload.dispatchId),
        sequence: activity.sequence,
        createdAtMs: activity.updatedAtMs ?? activity.createdAtMs,
        identity: activity.id,
        ordinal: index,
      })),
      ...lane.messageIds.map((messageId, index) => {
        const message = projection.messagesById[messageId]!;
        return {
          dispatchId: message.dispatchId ?? '',
          sequence: message.chronology?.roomEventSequence ?? message.sequence,
          createdAtMs: message.chronology?.createdAtMs ?? message.createdAtMs,
          identity: message.sourceEventId || message.sourceMessageId || message.id,
          ordinal: lane.activities.length + index,
        };
      }),
    ]
      .filter((item) => Boolean(item.dispatchId))
      .sort(compareRoomExecutionChronology)
      .at(-1);
    if (latestDispatch) lane.dispatchId = latestDispatch.dispatchId;
  }
  return {
    activities,
    lanes: [...lanes.values()],
    messageIds: orderedMessageIds,
    userMessageIds: orderedMessageIds.filter((messageId) => (
      projection.messagesById[messageId]?.role === 'user'
    )),
  };
}

function compareRoomExecutionChronology(
  left: { sequence?: number; createdAtMs: number; identity: string; ordinal: number },
  right: { sequence?: number; createdAtMs: number; identity: string; ordinal: number },
): number {
  // Historical projections may contain legacy entries without a Room event
  // sequence alongside current sequenced entries. Treat all legacy entries as
  // preceding the authoritative event stream so a delayed old attempt cannot
  // reclaim the card. This must remain one transitive total order: falling
  // back to timestamp whenever only one side lacks a sequence makes sort
  // results depend on the input permutation.
  if (left.sequence !== undefined || right.sequence !== undefined) {
    if (left.sequence === undefined) return -1;
    if (right.sequence === undefined) return 1;
    const sequenceOrder = left.sequence - right.sequence;
    if (sequenceOrder !== 0) return sequenceOrder;
  }
  const timeOrder = left.createdAtMs - right.createdAtMs;
  if (timeOrder !== 0) return timeOrder;
  const identityOrder = left.identity.localeCompare(right.identity);
  return identityOrder || left.ordinal - right.ordinal;
}

function taskLaneKey(
  rootId: string,
  participantId: string | null,
  taskId: string,
  executionPhase: number,
): string {
  return [
    rootId,
    participantId || 'participant',
    `task:${taskId}`,
    `phase:${executionPhase}`,
  ].join('\u001f');
}

function isRoomExecutionStartMessage(message: RoomMessageProjection): boolean {
  return message.role === 'user'
    && !message.answerToPostId
    && message.text.trim() === '开始行动';
}

function roomExecutionPhaseOrdinal(
  sequence: number | undefined,
  createdAtMs: number,
  boundaries: { sequence?: number; createdAtMs: number }[],
): number {
  return boundaries.filter((boundary) => {
    if (sequence !== undefined && boundary.sequence !== undefined) {
      return sequence > boundary.sequence;
    }
    return createdAtMs > boundary.createdAtMs;
  }).length;
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

/** Only governed reviews may leave Room for a participant Session.
 *
 * Clarification has one canonical owner: the structured Room question. Native
 * participant `user_input_required` events are rejected by the runtime and may
 * still be present in historical projections, so they must never revive a
 * second answer link here.
 */
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
    || ['memory_review', 'plan_review'].includes(requestKind);
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
  if (['intercom', 'work'].includes(textValue(activity.payload.activityKind))) return true;
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
