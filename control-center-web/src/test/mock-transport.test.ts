import { describe, expect, it, vi } from 'vitest';

import { agentEventFixture } from './fixtures/events';
import { MockControlTransport } from './mock-transport';

describe('MockControlTransport', () => {
  it('shares request validation, abort, and subscription semantics', async () => {
    const transport = new MockControlTransport({
      routes: { 'system.health': { ok: true } },
      now: () => 10,
    });
    await expect(transport.request({ pathId: 'system.health' })).resolves.toEqual({ ok: true });
    expect(transport.requests[0]).toMatchObject({ at: 10, request: { pathId: 'system.health' } });

    const controller = new AbortController();
    controller.abort();
    await expect(
      transport.request({ pathId: 'system.health', signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });

    const events: unknown[] = [];
    const snapshots: unknown[] = [];
    const cancel = transport.subscribe(
      {
        pathId: 'agent.session.events',
        params: { sessionId: 'session-1' },
        lastEventId: '',
      },
      { next: (event) => events.push(event), snapshotRequired: (event) => snapshots.push(event) },
    );
    transport.emit('agent.session.events', agentEventFixture(1, 'snapshot_required', {}));
    expect(events).toHaveLength(1);
    expect(snapshots).toHaveLength(1);
    cancel();
    expect(transport.activeSubscriptionCount()).toBe(0);
  });

  it('keeps the previous cursor when observer delivery fails', () => {
    const transport = new MockControlTransport();
    const reconnect = vi.fn();
    const error = vi.fn();
    let deliveries = 0;
    transport.subscribe(
      {
        pathId: 'agent.session.events',
        params: { sessionId: 'session-1' },
        lastEventId: 'session-1:8',
      },
      {
        next: () => {
          deliveries += 1;
          if (deliveries === 1) throw new Error('projection commit failed');
        },
        error,
        reconnect,
      },
    );

    expect(transport.emit(
      'agent.session.events',
      agentEventFixture(9, 'turn_completed', {}),
    )).toBe(0);
    expect(transport.emit(
      'agent.session.events',
      agentEventFixture(10, 'turn_completed', {}),
    )).toBe(0);
    transport.simulateReconnect('agent.session.events');
    expect(error).toHaveBeenCalledWith(expect.objectContaining({
      message: 'projection commit failed',
    }));
    expect(reconnect).toHaveBeenLastCalledWith({
      attempt: 1,
      delayMs: 20,
      lastEventId: 'session-1:8',
    });

    expect(transport.emit(
      'agent.session.events',
      agentEventFixture(9, 'turn_completed', {}),
    )).toBe(1);
    transport.simulateReconnect('agent.session.events');
    expect(reconnect).toHaveBeenLastCalledWith({
      attempt: 1,
      delayMs: 20,
      lastEventId: 'session-1:9',
    });
  });

  it('keeps the durable cursor after a transient snapshot-required control', () => {
    const transport = new MockControlTransport();
    const reconnect = vi.fn();
    transport.subscribe(
      {
        pathId: 'agent.session.events',
        params: { sessionId: 'session-1' },
        lastEventId: 'session-1:8',
      },
      { next: () => undefined, reconnect },
    );
    const control = {
      ...agentEventFixture(10, 'snapshot_required', {
        reason: 'event_replay_gap',
        afterEventId: 'session-1:8',
      }),
      eventId: 'session-1:snapshot-required:9',
      resumeToken: 'session-1:snapshot-required:9',
    };

    expect(transport.emit('agent.session.events', control)).toBe(1);
    transport.simulateReconnect('agent.session.events');

    expect(reconnect).toHaveBeenLastCalledWith({
      attempt: 1,
      delayMs: 20,
      lastEventId: 'session-1:8',
    });
  });
});
