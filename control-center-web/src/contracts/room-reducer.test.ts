import { describe, expect, it } from 'vitest';

import {
  appendOptimisticRoomMessage,
  createRoomProjection,
  reduceRoomEvent,
} from './room-reducer';
import { roomEventFixture as roomEvent } from '@/test/fixtures/events';

describe('RoomEventReducer', () => {
  it('projects participant deltas once and requests a snapshot on a gap', () => {
    const first = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'participant_delta', { delta: '并' }),
    );
    const second = reduceRoomEvent(
      first.state,
      roomEvent(2, 'participant_delta', { delta: '行' }),
    );
    const duplicate = reduceRoomEvent(
      second.state,
      roomEvent(2, 'participant_delta', { delta: '行' }),
    );
    const gap = reduceRoomEvent(second.state, roomEvent(4, 'turn_completed', {}));

    expect(duplicate.disposition).toBe('ignored-duplicate');
    expect(second.state.messagesById['room-message-1'].text).toBe('并行');
    expect(gap.disposition).toBe('snapshot-required');
    expect(gap.state.needsSnapshot).toBe(true);
  });

  it('merges optimistic room input by clientMessageId and keeps unknown events', () => {
    const optimistic = appendOptimisticRoomMessage(createRoomProjection('room-1'), {
      clientMessageId: 'room-client-1',
      text: '@智鼬 检查状态',
      nowMs: 1,
    });
    const merged = reduceRoomEvent(
      optimistic,
      roomEvent(1, 'user_message', {
        messageId: 'room-user-1',
        clientMessageId: 'room-client-1',
        text: '@智鼬 检查状态',
      }),
    ).state;
    const unknown = reduceRoomEvent(
      merged,
      roomEvent(2, 'future_room_vote', { result: 'kept' }),
    ).state;

    expect(merged.messageOrder).toEqual(['room-user-1']);
    expect(unknown.diagnostics[0]).toMatchObject({ eventType: 'future_room_vote' });
  });
});
