import { afterEach, describe, expect, it } from 'vitest';
import type { RoomEventSnapshot } from '@/contracts/room-reducer';
import { createRoomKernelProjection } from '@/contracts/room-kernel-reducer';
import { roomEventFixture } from '@/test/fixtures/events';

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

  it('retains the authoritative Kernel projection and sync freshness independently by Room', () => {
    const roomA = createRoomKernelProjection('room:a');
    roomA.lastSequence = 7;
    const roomB = createRoomKernelProjection('room:b');
    roomB.lastSequence = 3;
    const store = useRoomLiveStore.getState();

    store.setKernelProjection('room:a', roomA);
    store.setKernelProjection('room:b', roomB);
    store.setKernelSync('room:a', {
      state: 'reconnecting',
      detail: '正在恢复事件流',
      updatedAtMs: 120,
      failureAtMs: 140,
    });

    expect(useRoomLiveStore.getState().kernelProjections['room:a']).toBe(roomA);
    expect(useRoomLiveStore.getState().kernelProjections['room:b']).toBe(roomB);
    expect(useRoomLiveStore.getState().kernelSyncByRoomId['room:a']).toEqual({
      state: 'reconnecting',
      detail: '正在恢复事件流',
      updatedAtMs: 120,
      failureAtMs: 140,
    });
    const staleRoomA = createRoomKernelProjection('room:a');
    staleRoomA.lastSequence = 6;
    store.setKernelProjection('room:a', staleRoomA);
    expect(useRoomLiveStore.getState().kernelProjections['room:a']).toBe(roomA);

    store.remove('room:a');
    expect(useRoomLiveStore.getState().kernelProjections['room:a']).toBeUndefined();
    expect(useRoomLiveStore.getState().kernelSyncByRoomId['room:a']).toBeUndefined();
    expect(useRoomLiveStore.getState().kernelProjections['room:b']).toBe(roomB);
  });

  it('keeps a newer live projection when reconnect hydration returns an older snapshot', () => {
    const store = useRoomLiveStore.getState();
    store.applyEvents('room-1', [
      roomEventFixture(1, 'participant_status', { status: 'working' }),
    ]);
    const confirmed = roomProjection('room-1');
    const revision = useRoomLiveStore.getState().roomRevisions['room-1'];
    const staleSnapshot = {
      lastSequence: 0,
      room: { id: 'room-1' },
      resumeToken: '',
    } as unknown as RoomEventSnapshot;

    expect(store.replaySnapshot('room-1', staleSnapshot)).toBe(false);
    expect(roomProjection('room-1')).toBe(confirmed);
    expect(roomProjection('room-1').resumeToken).toBe('room-1:1');
    expect(useRoomLiveStore.getState().roomRevisions['room-1']).toBe(revision);
  });

  it('drops every projection only when an explicit reset is requested', () => {
    const store = useRoomLiveStore.getState();
    store.ensure('room:a');
    store.ensure('room:b');
    store.reset();

    expect(useRoomLiveStore.getState().projections).toEqual({});
    expect(useRoomLiveStore.getState().roomRevisions).toEqual({});
    expect(useRoomLiveStore.getState().turnRevisions).toEqual({});
    expect(useRoomLiveStore.getState().kernelProjections).toEqual({});
    expect(useRoomLiveStore.getState().kernelSyncByRoomId).toEqual({});
  });
});
