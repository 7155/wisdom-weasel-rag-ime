import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { roomEventFixture } from '@/test/fixtures/events';
import { MockControlTransport } from '@/test/mock-transport';
import type { ControlEventObserver, ControlSubscription } from '@/platform/transport';
import { roomProjection, useRoomLiveStore } from '../state/live-store';
import { useRoomLiveSession } from './use-room-live-session';

afterEach(() => {
  cleanup();
  useRoomLiveStore.getState().reset();
  vi.useRealTimers();
});

describe('useRoomLiveSession snapshot recovery', () => {
  it('resumes from the confirmed live cursor when a reconnect snapshot is older', async () => {
    const store = useRoomLiveStore.getState();
    store.applyEvents('room-1', [
      roomEventFixture(1, 'participant_status', { status: 'working' }),
      roomEventFixture(2, 'participant_status', { status: 'working' }),
    ]);
    const onSnapshot = vi.fn();
    const onConnectionError = vi.fn();
    const transport = new MockControlTransport({
      routes: {
        'agent.room.snapshot': roomSnapshot([
          roomEventFixture(1, 'participant_status', { status: 'working' }),
        ]),
      },
    });

    const { unmount } = renderHook(() => useRoomLiveSession({
      roomId: 'room-1',
      transport,
      onLoadingChange: vi.fn(),
      onSnapshot,
      onMetadata: vi.fn(),
      onConnectionRestored: vi.fn(),
      onConnectionError,
      onRecoveryState: vi.fn(),
      onEvents: vi.fn(),
    }));

    await waitFor(() => {
      const error = onConnectionError.mock.calls[0]?.[1];
      if (error instanceof Error) throw error;
      expect(transport.subscriptionCalls).toHaveLength(1);
    });
    expect(transport.subscriptionCalls[0]?.request.lastEventId).toBe('room-1:2');
    expect(roomProjection('room-1').lastSequence).toBe(2);
    expect(onSnapshot).not.toHaveBeenCalled();
    unmount();
  });

  it('recovers a transient stream error without requiring a click', async () => {
    vi.useFakeTimers();
    const onConnectionRestored = vi.fn();
    const onConnectionError = vi.fn();
    const onRecoveryState = vi.fn();
    let snapshotCalls = 0;
    const transport = new ReconnectableMockControlTransport({
      routes: {
        'agent.room.snapshot': () => {
          snapshotCalls += 1;
          return roomSnapshot([]);
        },
      },
    });

    const { unmount } = renderHook(() => useRoomLiveSession({
      roomId: 'room-1',
      transport,
      onLoadingChange: vi.fn(),
      onSnapshot: vi.fn(),
      onMetadata: vi.fn(),
      onConnectionRestored,
      onConnectionError,
      onRecoveryState,
      onEvents: vi.fn(),
    }));

    await flushAsyncWork();
    expect(onConnectionRestored).toHaveBeenCalledTimes(1);
    expect(onRecoveryState).toHaveBeenLastCalledWith('room-1', 'synced');

    act(() => transport.disconnect(new Error('stream interrupted')));
    expect(onConnectionError).toHaveBeenCalledTimes(1);
    expect(onConnectionRestored).toHaveBeenCalledTimes(1);
    expect(onRecoveryState).toHaveBeenLastCalledWith('room-1', 'recovering');

    await act(async () => vi.advanceTimersByTimeAsync(999));
    expect(snapshotCalls).toBe(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    await flushAsyncWork();
    expect(snapshotCalls).toBe(2);
    expect(onConnectionRestored).toHaveBeenCalledTimes(2);
    expect(onRecoveryState).toHaveBeenLastCalledWith('room-1', 'synced');
    unmount();
  });

  it('automatically retries a failed snapshot after a bounded delay', async () => {
    vi.useFakeTimers();
    let snapshotCalls = 0;
    const onConnectionRestored = vi.fn();
    const onRecoveryState = vi.fn();
    const transport = new MockControlTransport({
      routes: {
        'agent.room.snapshot': () => {
          snapshotCalls += 1;
          if (snapshotCalls === 1) throw new Error('gateway restarting');
          return roomSnapshot([]);
        },
      },
    });

    const { unmount } = renderHook(() => useRoomLiveSession({
      roomId: 'room-1',
      transport,
      onLoadingChange: vi.fn(),
      onSnapshot: vi.fn(),
      onMetadata: vi.fn(),
      onConnectionRestored,
      onConnectionError: vi.fn(),
      onRecoveryState,
      onEvents: vi.fn(),
    }));

    await flushAsyncWork();
    expect(snapshotCalls).toBe(1);
    expect(onRecoveryState).toHaveBeenLastCalledWith('room-1', 'recovering');
    await act(async () => vi.advanceTimersByTimeAsync(999));
    expect(snapshotCalls).toBe(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    await flushAsyncWork();
    expect(snapshotCalls).toBe(2);
    expect(onConnectionRestored).toHaveBeenCalledTimes(1);
    expect(onRecoveryState).toHaveBeenLastCalledWith('room-1', 'synced');
    unmount();
  });

  it('cancels a scheduled recovery when the Room unmounts', async () => {
    vi.useFakeTimers();
    let snapshotCalls = 0;
    const transport = new MockControlTransport({
      routes: {
        'agent.room.snapshot': () => {
          snapshotCalls += 1;
          throw new Error('gateway unavailable');
        },
      },
    });

    const { unmount } = renderHook(() => useRoomLiveSession({
      roomId: 'room-1',
      transport,
      onLoadingChange: vi.fn(),
      onSnapshot: vi.fn(),
      onMetadata: vi.fn(),
      onConnectionRestored: vi.fn(),
      onConnectionError: vi.fn(),
      onRecoveryState: vi.fn(),
      onEvents: vi.fn(),
    }));

    await flushAsyncWork();
    expect(snapshotCalls).toBe(1);
    unmount();
    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(snapshotCalls).toBe(1);
  });

  it('resets the recovery delay after a successful open', async () => {
    vi.useFakeTimers();
    let snapshotCalls = 0;
    const transport = new ReconnectableMockControlTransport({
      routes: {
        'agent.room.snapshot': () => {
          snapshotCalls += 1;
          return roomSnapshot([]);
        },
      },
    });

    const { unmount } = renderHook(() => useRoomLiveSession({
      roomId: 'room-1',
      transport,
      onLoadingChange: vi.fn(),
      onSnapshot: vi.fn(),
      onMetadata: vi.fn(),
      onConnectionRestored: vi.fn(),
      onConnectionError: vi.fn(),
      onRecoveryState: vi.fn(),
      onEvents: vi.fn(),
    }));

    await flushAsyncWork();
    act(() => transport.disconnect(new Error('first interruption')));
    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    await flushAsyncWork();
    expect(snapshotCalls).toBe(2);

    act(() => transport.disconnect(new Error('second interruption')));
    await act(async () => vi.advanceTimersByTimeAsync(999));
    expect(snapshotCalls).toBe(2);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    await flushAsyncWork();
    expect(snapshotCalls).toBe(3);
    unmount();
  });

  it('coalesces repeated manual retries while a snapshot request is active', async () => {
    let snapshotCalls = 0;
    let resolveFirstSnapshot: ((value: ReturnType<typeof roomSnapshot>) => void) | undefined;
    const firstSnapshot = new Promise<ReturnType<typeof roomSnapshot>>((resolve) => {
      resolveFirstSnapshot = resolve;
    });
    const transport = new MockControlTransport({
      routes: {
        'agent.room.snapshot': () => {
          snapshotCalls += 1;
          return snapshotCalls === 1 ? firstSnapshot : roomSnapshot([]);
        },
      },
    });

    const { result, unmount } = renderHook(() => useRoomLiveSession({
      roomId: 'room-1',
      transport,
      onLoadingChange: vi.fn(),
      onSnapshot: vi.fn(),
      onMetadata: vi.fn(),
      onConnectionRestored: vi.fn(),
      onConnectionError: vi.fn(),
      onRecoveryState: vi.fn(),
      onEvents: vi.fn(),
    }));

    expect(snapshotCalls).toBe(1);
    act(() => {
      result.current();
      result.current();
      result.current();
    });
    expect(snapshotCalls).toBe(1);
    await act(async () => {
      resolveFirstSnapshot?.(roomSnapshot([]));
      await firstSnapshot;
    });
    await flushAsyncWork();
    expect(snapshotCalls).toBe(2);
    unmount();
  });

  it('offers manual recovery after sustained failures and resets the pending backoff', async () => {
    vi.useFakeTimers();
    let snapshotCalls = 0;
    let gatewayReady = false;
    const onRecoveryState = vi.fn();
    const transport = new MockControlTransport({
      routes: {
        'agent.room.snapshot': () => {
          snapshotCalls += 1;
          if (!gatewayReady) throw new Error('gateway unavailable');
          return roomSnapshot([]);
        },
      },
    });

    const { result, unmount } = renderHook(() => useRoomLiveSession({
      roomId: 'room-1',
      transport,
      onLoadingChange: vi.fn(),
      onSnapshot: vi.fn(),
      onMetadata: vi.fn(),
      onConnectionRestored: vi.fn(),
      onConnectionError: vi.fn(),
      onRecoveryState,
      onEvents: vi.fn(),
    }));

    await flushAsyncWork();
    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    await flushAsyncWork();
    await act(async () => vi.advanceTimersByTimeAsync(2_000));
    await flushAsyncWork();
    expect(snapshotCalls).toBe(3);
    expect(onRecoveryState).toHaveBeenLastCalledWith('room-1', 'failed');

    gatewayReady = true;
    act(() => result.current());
    await flushAsyncWork();
    expect(snapshotCalls).toBe(4);
    expect(onRecoveryState).toHaveBeenLastCalledWith('room-1', 'synced');
    await act(async () => vi.advanceTimersByTimeAsync(15_000));
    expect(snapshotCalls).toBe(4);
    unmount();
  });
});

class ReconnectableMockControlTransport extends MockControlTransport {
  private roomObserver: ControlEventObserver<unknown> | undefined;

  override subscribe<Event = unknown>(
    request: ControlSubscription,
    observer: ControlEventObserver<Event>,
  ): () => void {
    this.roomObserver = observer as ControlEventObserver<unknown>;
    return super.subscribe(request, observer);
  }

  disconnect(error: Error): void {
    this.roomObserver?.error?.(error);
  }

}

async function flushAsyncWork(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}


function roomSnapshot(events: ReturnType<typeof roomEventFixture>[]) {
  const lastSequence = events.at(-1)?.sequence ?? 0;
  return {
    schemaVersion: 'rag-ime.agent-room-snapshot.v1',
    ok: true,
    room: {
      schemaVersion: 'rag-ime.agent-room.v1',
      id: 'room-1',
      title: '协作恢复',
      status: 'active',
      executionMode: 'workspace_managed',
      routingPolicy: 'moderator',
      moderatorParticipantId: 'participant-1',
      workspaceRoots: ['/Volumes/work/learnA'],
      createdAtMs: 1,
      updatedAtMs: 2,
      lastEventSequence: lastSequence,
      participants: [{
        schemaVersion: 'rag-ime.agent-participant.v1',
        id: 'participant-1',
        roomId: 'room-1',
        sessionId: 'session-room-1',
        roleId: 'companion-present-v1',
        roleVersion: '1',
        displayName: '澄',
        collaborationRole: 'coordinator',
        status: 'active',
        ordinal: 0,
        createdAtMs: 1,
        lastSpokeAtMs: null,
      },
      {
        schemaVersion: 'rag-ime.agent-participant.v1',
        id: 'participant-2',
        roomId: 'room-1',
        sessionId: 'session-room-2',
        roleId: 'companion-firstlight-v1',
        roleVersion: '1',
        displayName: '澄·初',
        collaborationRole: 'reviewer',
        status: 'active',
        ordinal: 1,
        createdAtMs: 1,
        lastSpokeAtMs: null,
      },
      ],
    },
    events: events.map((event) => Object.fromEntries(
      Object.entries(event).filter(([key]) => key !== 'streamKind'),
    )),
    firstSequence: events[0]?.sequence ?? 0,
    lastSequence,
    resumeToken: lastSequence ? `room-1:${lastSequence}` : '',
    truncated: false,
  };
}
