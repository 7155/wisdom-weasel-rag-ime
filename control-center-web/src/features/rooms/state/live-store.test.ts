import { afterEach, describe, expect, it } from 'vitest';

import { roomProjection, useRoomLiveStore } from './live-store';

describe('Room live store', () => {
  afterEach(() => useRoomLiveStore.getState().reset());

  it('isolates projections by Room and retains in-flight messages across navigation', () => {
    const store = useRoomLiveStore.getState();
    store.appendOptimistic('room:a', {
      clientMessageId: 'client:a',
      text: '继续执行',
      nowMs: 10,
    });

    expect(roomProjection('room:a').messageOrder).toEqual(['local-room:client:a']);
    expect(roomProjection('room:b').messageOrder).toEqual([]);
    expect(useRoomLiveStore.getState().roomRevisions['room:a']).toBe(1);
    expect(useRoomLiveStore.getState().roomRevisions['room:b']).toBeUndefined();
  });

  it('increments only the changed turn revision', () => {
    const store = useRoomLiveStore.getState();
    store.appendOptimistic('room:a', {
      clientMessageId: 'client:first',
      text: '第一条',
      nowMs: 10,
    });
    store.appendOptimistic('room:a', {
      clientMessageId: 'client:second',
      text: '第二条',
      nowMs: 20,
    });

    const [firstTurnId, secondTurnId] = roomProjection('room:a').turnOrder;
    const before = useRoomLiveStore.getState().turnRevisions['room:a'];
    expect(before?.[firstTurnId!]).toBe(1);
    expect(before?.[secondTurnId!]).toBe(1);

    store.discardOptimistic('room:a', 'client:first');

    const after = useRoomLiveStore.getState().turnRevisions['room:a'];
    expect(after?.[firstTurnId!]).toBe(2);
    expect(after?.[secondTurnId!]).toBe(1);
    expect(roomProjection('room:a').turnOrder).toEqual([secondTurnId]);
  });

  it('drops every projection only when an explicit reset is requested', () => {
    const store = useRoomLiveStore.getState();
    store.ensure('room:a');
    store.ensure('room:b');
    store.reset();

    expect(useRoomLiveStore.getState().projections).toEqual({});
    expect(useRoomLiveStore.getState().roomRevisions).toEqual({});
    expect(useRoomLiveStore.getState().turnRevisions).toEqual({});
  });
});
