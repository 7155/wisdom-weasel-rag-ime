import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { agentEventFixture } from '@/test/fixtures/events';
import { MockControlTransport } from '@/test/mock-transport';
import { useAgentLiveStore } from '../state/live-store';
import { useAgentLiveSession } from './use-agent-live-session';

const SESSION_ID = 'session-shared';

afterEach(() => {
  cleanup();
  useAgentLiveStore.getState().clear(SESSION_ID);
  vi.useRealTimers();
});

describe('useAgentLiveSession shared ownership', () => {
  it('uses one snapshot and stream while two windows observe the same event', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.session.snapshot': {
          lastSequence: 0,
          resumeToken: `${SESSION_ID}:0`,
          status: 'idle',
          messages: [],
          liveEvents: [],
        },
      },
    });
    const firstEvent = vi.fn();
    const secondEvent = vi.fn();
    const firstEvents = vi.fn();
    const secondEvents = vi.fn();

    const firstWindow = renderHook(() => useAgentLiveSession({
      sessionId: SESSION_ID,
      transport,
      onEvent: firstEvent,
      onEvents: firstEvents,
    }));
    const secondWindow = renderHook(() => useAgentLiveSession({
      sessionId: SESSION_ID,
      transport,
      onEvent: secondEvent,
      onEvents: secondEvents,
    }));

    await waitFor(() => expect(transport.subscriptionCalls).toHaveLength(1));
    expect(transport.requests.filter(({ request }) => (
      request.pathId === 'agent.session.snapshot'
    ))).toHaveLength(1);
    expect(transport.activeSubscriptionCount()).toBe(1);

    const event = agentEventFixture(1, 'text_delta', {
      delta: '共享实时回答',
      replaceBlock: true,
    });
    const rawEvent = Object.fromEntries(
      Object.entries({
        ...event,
        eventId: `${SESSION_ID}:1`,
        sessionId: SESSION_ID,
        resumeToken: `${SESSION_ID}:1`,
      }).filter(([key]) => key !== 'streamKind'),
    );
    act(() => {
      expect(transport.emit('agent.session.events', rawEvent)).toBe(1);
    });
    expect(firstEvent).toHaveBeenCalledTimes(1);
    expect(secondEvent).toHaveBeenCalledTimes(1);
    expect(firstEvent).toHaveBeenCalledWith(expect.objectContaining({
      eventId: `${SESSION_ID}:1`,
      sessionId: SESSION_ID,
    }));
    expect(secondEvent).toHaveBeenCalledWith(expect.objectContaining({
      eventId: `${SESSION_ID}:1`,
      sessionId: SESSION_ID,
    }));
    await waitFor(() => {
      expect(firstEvents).toHaveBeenCalledTimes(1);
      expect(secondEvents).toHaveBeenCalledTimes(1);
    });

    firstWindow.unmount();
    expect(transport.activeSubscriptionCount()).toBe(1);
    secondWindow.unmount();
    expect(transport.activeSubscriptionCount()).toBe(0);
  });

  it('recovers a dropped shared stream once for every observing window', async () => {
    let snapshotCalls = 0;
    const transport = new MockControlTransport({
      routes: {
        'agent.session.snapshot': () => {
          snapshotCalls += 1;
          return {
            lastSequence: 0,
            resumeToken: `${SESSION_ID}:0`,
            status: 'idle',
            messages: [],
            liveEvents: [],
          };
        },
      },
    });
    const firstError = vi.fn();
    const secondError = vi.fn();
    const firstRestored = vi.fn();
    const secondRestored = vi.fn();
    const firstWindow = renderHook(() => useAgentLiveSession({
      sessionId: SESSION_ID,
      transport,
      onConnectionError: firstError,
      onConnectionRestored: firstRestored,
    }));
    const secondWindow = renderHook(() => useAgentLiveSession({
      sessionId: SESSION_ID,
      transport,
      onConnectionError: secondError,
      onConnectionRestored: secondRestored,
    }));
    await waitFor(() => expect(transport.activeSubscriptionCount()).toBe(1));
    vi.useFakeTimers();

    const interruption = new Error('stream interrupted');
    act(() => transport.fail('agent.session.events', interruption));
    expect(firstError).toHaveBeenCalledWith(SESSION_ID, interruption);
    expect(secondError).toHaveBeenCalledWith(SESSION_ID, interruption);
    expect(snapshotCalls).toBe(1);

    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    await act(async () => Promise.resolve());
    expect(snapshotCalls).toBe(2);
    expect(transport.subscriptionCalls).toHaveLength(2);
    expect(transport.activeSubscriptionCount()).toBe(1);
    expect(firstRestored).toHaveBeenLastCalledWith(SESSION_ID);
    expect(secondRestored).toHaveBeenLastCalledWith(SESSION_ID);
    firstWindow.unmount();
    secondWindow.unmount();
  });
});
