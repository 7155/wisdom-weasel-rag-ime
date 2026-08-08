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
  dispatchId: string;
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
  return projection.turnOrder.filter((turnId) => turnId !== 'unscoped');
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
    const participantId = activity.participantId
      || textValue(activity.payload.targetParticipantId)
      || null;
    const lane = lanes.get(identity.key) ?? {
      key: identity.key,
      rootId: identity.rootId,
      dispatchId: identity.dispatchId,
      participantId,
      sourceSessionId: activity.sourceSessionId,
      activities: [],
      messageIds: [],
    };
    lane.activities.push(activity);
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
    const exactKey = message.dispatchId
      ? [
          message.rootId || turn.rootId || turnId,
          message.participantId || message.sourceSessionId || 'participant',
          message.dispatchId,
        ].join('\u001f')
      : '';
    const existingKey = exactKey && lanes.has(exactKey)
      ? exactKey
      : participantLaneKeys
          .get(participantKey(message.participantId, message.sourceSessionId))
          ?.at(-1);
    const laneKey = existingKey ?? [
      turn.rootId || turnId,
      message.participantId || message.sourceSessionId || 'participant',
      message.dispatchId || message.id,
    ].join('\u001f');
    const lane = lanes.get(laneKey) ?? {
      key: laneKey,
      rootId: message.rootId || turn.rootId || turnId,
      dispatchId: message.dispatchId || '',
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
  return {
    activities,
    lanes: [...lanes.values()],
    messageIds: orderedMessageIds,
    userMessageIds: orderedMessageIds.filter((messageId) => (
      projection.messagesById[messageId]?.role === 'user'
    )),
  };
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
