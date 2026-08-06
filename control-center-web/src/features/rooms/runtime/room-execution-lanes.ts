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
  return projection.turnOrder.filter((turnId) => turnId !== 'unscoped');
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
  const lanes = new Map<string, RoomExecutionLane>();
  const participantLaneKeys = new Map<string, string[]>();
  const dispatchLaneKeys = new Map<string, string>();

  for (const activity of activities) {
    const sourceIdentity = roomActivityLaneIdentity(activity);
    const taskId = sourceIdentity.taskId
      || taskIdByDispatchId[sourceIdentity.dispatchId]
      || '';
    const identity = {
      ...sourceIdentity,
      taskId,
      key: taskId
        ? `${sourceIdentity.rootId}\u001f${sourceIdentity.participantId}\u001f${taskId}`
        : sourceIdentity.key,
    };
    const participantId = activity.participantId
      || textValue(activity.payload.targetParticipantId)
      || null;
    const participantIdentity = participantKey(participantId, activity.sourceSessionId);
    // Work-item lifecycle updates may omit Dispatch/Task ids even though they
    // belong to the same participant Session. Keep them in the existing role
    // card instead of introducing a second avatar/card for one assignment.
    const hasAuthoritativeWorkIdentity = Boolean(
      textValue(activity.payload.taskId) || textValue(activity.payload.dispatchId),
    );
    const existingParticipantLane = !hasAuthoritativeWorkIdentity
      ? participantLaneKeys.get(participantIdentity)?.at(-1)
      : undefined;
    const laneKey = existingParticipantLane ?? identity.key;
    const lane = lanes.get(laneKey) ?? {
      key: laneKey,
      rootId: identity.rootId,
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
    if (message.role === 'user') {
      continue;
    }
    const dispatchKey = message.dispatchId
      ? dispatchLaneKeys.get(message.dispatchId) ?? ''
      : '';
    const exactKey = message.dispatchId
      ? [
          message.rootId || turn.rootId || turnId,
          message.participantId || message.sourceSessionId || 'participant',
          message.dispatchId,
        ].join('\u001f')
      : '';
    const existingKey = dispatchKey
      || (exactKey && lanes.has(exactKey)
      ? exactKey
      : participantLaneKeys
          .get(participantKey(message.participantId, message.sourceSessionId))
          ?.at(-1));
    const laneKey = existingKey ?? [
      turn.rootId || turnId,
      message.participantId || message.sourceSessionId || 'participant',
      message.dispatchId || message.id,
    ].join('\u001f');
    const lane = lanes.get(laneKey) ?? {
      key: laneKey,
      rootId: message.rootId || turn.rootId || turnId,
      taskId: '',
      dispatchId: message.dispatchId || '',
      dispatchIds: message.dispatchId ? [message.dispatchId] : [],
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
