import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { roomEventFixture } from '@/test/fixtures/events';
import { MockControlTransport } from '@/test/mock-transport';
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
});

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
