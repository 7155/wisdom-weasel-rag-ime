import { afterEach, describe, expect, it } from 'vitest';
import type { RoomEventPage, RoomEventSnapshot } from '@/contracts/room-reducer';
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

  it('prepends bounded history pages and preserves them across a newer snapshot', () => {
    const store = useRoomLiveStore.getState();
    const recent = [
      roomEventFixture(3, 'participant_status', { status: 'working' }),
      roomEventFixture(4, 'participant_status', { status: 'completed' }),
    ];
    expect(store.replaySnapshot(
      'room-1',
      roomHistorySnapshot(recent, 3, 4),
    )).toBe(true);
    expect(useRoomLiveStore.getState().historyByRoomId['room-1']?.hasMore).toBe(true);

    const older = [
      roomEventFixture(1, 'participant_status', { status: 'assigned' }),
      roomEventFixture(2, 'participant_status', { status: 'accepted' }),
    ];
    const page = {
      schemaVersion: 'rag-ime.agent-room-event-page.v1',
      ok: true,
      roomId: 'room-1',
      items: older,
      firstSequence: 1,
      lastSequence: 2,
      nextBeforeSequence: 0,
      hasMore: false,
      retainedFirstSequence: 1,
      retainedLastSequence: 4,
      retainedPrefixTruncated: false,
    } satisfies RoomEventPage;

    expect(store.prependHistory('room-1', page)).toBe(true);
    expect(
      useRoomLiveStore.getState().historyByRoomId['room-1']?.events.map((event) => event.sequence),
    ).toEqual([1, 2, 3, 4]);

    expect(store.replaySnapshot(
      'room-1',
      roomHistorySnapshot([
        roomEventFixture(4, 'participant_status', { status: 'completed' }),
        roomEventFixture(5, 'turn_completed', {}),
      ], 4, 5),
    )).toBe(true);
    expect(
      useRoomLiveStore.getState().historyByRoomId['room-1']?.events.map((event) => event.sequence),
    ).toEqual([1, 2, 3, 4, 5]);
    expect(useRoomLiveStore.getState().historyByRoomId['room-1']?.hasMore).toBe(false);
  });

  it('keeps explicitly loaded history beyond the live retention window', () => {
    const store = useRoomLiveStore.getState();
    const recent = Array.from({ length: 2_000 }, (_value, index) => (
      roomEventFixture(index + 201, 'participant_status', { status: 'working' })
    ));
    expect(store.replaySnapshot(
      'room-1',
      roomHistorySnapshot(recent, 201, 2_200),
    )).toBe(true);

    const older = Array.from({ length: 200 }, (_value, index) => (
      roomEventFixture(index + 1, 'participant_status', { status: 'completed' })
    ));
    const page = {
      schemaVersion: 'rag-ime.agent-room-event-page.v1',
      ok: true,
      roomId: 'room-1',
      items: older,
      firstSequence: 1,
      lastSequence: 200,
      nextBeforeSequence: 0,
      hasMore: false,
      retainedFirstSequence: 1,
      retainedLastSequence: 2_200,
      retainedPrefixTruncated: false,
    } satisfies RoomEventPage;

    expect(store.prependHistory('room-1', page)).toBe(true);
    const history = useRoomLiveStore.getState().historyByRoomId['room-1'];
    expect(history?.events).toHaveLength(2_200);
    expect(history?.events[0]?.sequence).toBe(1);
    expect(history?.events.at(-1)?.sequence).toBe(2_200);
    expect(history?.hasMore).toBe(false);
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

function roomHistorySnapshot(
  events: RoomEventSnapshot['events'],
  firstSequence: number,
  lastSequence: number,
): RoomEventSnapshot {
  return {
    schemaVersion: 'rag-ime.agent-room-snapshot.v1',
    ok: true,
    room: {
      id: 'room-1',
      lastEventSequence: lastSequence,
    },
    events,
    firstSequence,
    lastSequence,
    resumeToken: `room-1:${lastSequence}`,
    truncated: firstSequence > 1,
  } as unknown as RoomEventSnapshot;
}
