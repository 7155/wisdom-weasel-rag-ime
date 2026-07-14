import { describe, expect, it } from 'vitest';

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
});
