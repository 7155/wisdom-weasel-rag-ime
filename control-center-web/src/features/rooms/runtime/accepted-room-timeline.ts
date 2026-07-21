import {
  reduceRoomEvent,
  type RoomProjectionState,
} from '@/contracts/room-reducer';
import { parseRoomEvent } from '@/contracts/validators';

/** Merge the POST acknowledgement without racing the same SSE events. */
export function mergeAcceptedRoomTimeline(
  state: RoomProjectionState,
  response: unknown,
): RoomProjectionState {
  const value = record(response);
  const events = Array.isArray(value.timelineEvents)
    ? value.timelineEvents
    : [];
  let next = state;
  for (const item of events) {
    let event;
    try {
      event = parseRoomEvent(item);
    } catch {
      continue;
    }
    const reduced = reduceRoomEvent(next, event);
    if (reduced.disposition === 'snapshot-required') return state;
    if (reduced.disposition === 'applied') next = reduced.state;
  }
  return next;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
