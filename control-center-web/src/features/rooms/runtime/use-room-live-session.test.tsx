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

  it('clears a transient stream error only after the reconnect opens', async () => {
    const onConnectionRestored = vi.fn();
    const onConnectionError = vi.fn();
    const onRecoveryState = vi.fn();
    const transport = new ReconnectableMockControlTransport({
      routes: {
        'agent.room.snapshot': roomSnapshot([]),
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

    await waitFor(() => expect(onConnectionRestored).toHaveBeenCalledTimes(1));
    expect(onRecoveryState).toHaveBeenLastCalledWith('room-1', 'synced');

    act(() => transport.disconnect(new Error('stream interrupted')));
    expect(onConnectionError).toHaveBeenCalledTimes(1);
    expect(onConnectionRestored).toHaveBeenCalledTimes(1);

    act(() => transport.reopen('room-1:0'));
    expect(onConnectionRestored).toHaveBeenCalledTimes(2);
    expect(onRecoveryState).toHaveBeenLastCalledWith('room-1', 'synced');
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

  reopen(lastEventId: string): void {
    this.roomObserver?.open?.(lastEventId);
  }
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
