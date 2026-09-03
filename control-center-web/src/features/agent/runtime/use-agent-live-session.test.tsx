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


  it('applies an equal-sequence idle snapshot to settle stale running state', async () => {
    let snapshotCalls = 0;
    const delta = agentEventFixture(1, 'text_delta', {
      delta: '重启前仍显示为流式输出',
      replaceBlock: true,
    });
    const liveEvent = {
      ...delta,
      eventId: `${SESSION_ID}:1`,
      sessionId: SESSION_ID,
      resumeToken: `${SESSION_ID}:1`,
    };
    const transport = new MockControlTransport({
      routes: {
        'agent.session.snapshot': () => {
          snapshotCalls += 1;
          return snapshotCalls === 1
            ? {
                lastSequence: 1,
                resumeToken: `${SESSION_ID}:1`,
                status: 'busy',
                messages: [],
                liveEvents: [liveEvent],
                partial: true,
                snapshotScope: 'recent',
                runtimeQuiescent: false,
              }
            : {
                lastSequence: 1,
                resumeToken: `${SESSION_ID}:1`,
                status: 'idle',
                messages: [],
                liveEvents: [],
                partial: true,
                snapshotScope: 'recent',
                runtimeQuiescent: true,
              };
        },
      },
    });
    const window = renderHook(() => useAgentLiveSession({
      sessionId: SESSION_ID,
      transport,
    }));
    await waitFor(() => expect(transport.activeSubscriptionCount()).toBe(1));
    expect(useAgentLiveStore.getState().projections[SESSION_ID]?.turnsById['turn-1']?.status)
      .toBe('running');
    vi.useFakeTimers();

    act(() => transport.fail('agent.session.events', new Error('stream interrupted')));
    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    await act(async () => Promise.resolve());

    expect(snapshotCalls).toBe(2);
    expect(useAgentLiveStore.getState().projections[SESSION_ID]?.turnsById['turn-1']?.status)
      .toBe('completed');
    window.unmount();
  });
  it('keeps retrying after the first recovery snapshot fails during a Runtime restart', async () => {
    let snapshotCalls = 0;
    const transport = new MockControlTransport({
      routes: {
        'agent.session.snapshot': () => {
          snapshotCalls += 1;
          if (snapshotCalls === 2) throw new Error('gateway restarting');
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
    const snapshotError = vi.fn();
    const restored = vi.fn();
    const window = renderHook(() => useAgentLiveSession({
      sessionId: SESSION_ID,
      transport,
      onSnapshotError: snapshotError,
      onConnectionRestored: restored,
    }));
    await waitFor(() => expect(transport.activeSubscriptionCount()).toBe(1));
    vi.useFakeTimers();

    act(() => transport.fail('agent.session.events', new Error('stream interrupted')));
    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    expect(snapshotCalls).toBe(2);
    expect(snapshotError).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: SESSION_ID,
      error: expect.objectContaining({ message: 'gateway restarting' }),
    }));

    await act(async () => vi.advanceTimersByTimeAsync(2_000));
    await act(async () => Promise.resolve());
    expect(snapshotCalls).toBe(3);
    expect(transport.activeSubscriptionCount()).toBe(1);
    expect(restored).toHaveBeenLastCalledWith(SESSION_ID);
    window.unmount();
  });
});
