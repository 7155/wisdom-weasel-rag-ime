import { describe, expect, it } from 'vitest';

import { createEventBatcher, type BatchScheduler } from './batching';
import { createAgentProjection, reduceAgentEvents } from './agent-reducer';
import { agentEventFixture as agentEvent } from '@/test/fixtures/events';

describe('delta batching', () => {
  it('commits a 200-delta burst far fewer times than the event count', () => {
    const scheduler = new ManualScheduler();
    let state = createAgentProjection('session-1');
    let commits = 0;
    const batcher = createEventBatcher({
      scheduler,
      intervalMs: 20,
      isDelta: (event: ReturnType<typeof agentEvent>) => event.eventType === 'text_delta',
      commit(events: readonly ReturnType<typeof agentEvent>[]) {
        state = reduceAgentEvents(state, events);
        commits += 1;
      },
    });

    for (let sequence = 1; sequence <= 200; sequence += 1) {
      batcher.push(agentEvent(sequence, 'text_delta', { delta: '字' }));
    }
    expect(batcher.pendingCount).toBe(200);
    expect(commits).toBe(0);
    scheduler.flushAll();

    expect(commits).toBe(1);
    expect(commits).toBeLessThan(200 / 10);
    expect(state.lastSequence).toBe(200);
    expect(
      String(state.messagesById['turn-1:assistant'].blocks[0].data.text),
    ).toHaveLength(200);
  });

  it('flushes pending deltas before a terminal event to preserve ordering', () => {
    const scheduler = new ManualScheduler();
    const commits: string[][] = [];
    const batcher = createEventBatcher({
      scheduler,
      isDelta: (event: { eventType: string }) => event.eventType === 'text_delta',
      commit: (events: readonly { eventType: string }[]) =>
        commits.push(events.map((event) => event.eventType)),
    });
    batcher.push({ eventType: 'text_delta' });
    batcher.push({ eventType: 'turn_completed' });
    expect(commits).toEqual([['text_delta'], ['turn_completed']]);
  });
});

class ManualScheduler implements BatchScheduler<number> {
  private callbacks = new Map<number, () => void>();
  private nextId = 1;

  schedule(callback: () => void): number {
    const id = this.nextId++;
    this.callbacks.set(id, callback);
    return id;
  }

  cancel(handle: number): void {
    this.callbacks.delete(handle);
  }

  flushAll(): void {
    const callbacks = [...this.callbacks.values()];
    this.callbacks.clear();
    for (const callback of callbacks) callback();
  }
}
