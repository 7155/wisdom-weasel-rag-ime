import type {
  PendingRoomQuestionProjection,
  RoomActivityProjection,
  RoomProjectionState,
} from '@/contracts/room-reducer';

export type PendingRoomQuestion = PendingRoomQuestionProjection;

export function latestPendingGroupedRoomInput(
  projection?: RoomProjectionState,
): RoomActivityProjection | undefined {
  if (!projection) return undefined;
  for (let index = projection.activityOrder.length - 1; index >= 0; index -= 1) {
    const activity = projection.activitiesById[projection.activityOrder[index]!];
    if (
      activity?.status === 'waiting'
      && activity.payload.requestKind === 'grouped_questions'
      && typeof activity.payload.requestId === 'string'
      && activity.payload.requestId.trim()
      && activity.sourceSessionId.trim()
    ) return activity;
  }
  return undefined;
}
