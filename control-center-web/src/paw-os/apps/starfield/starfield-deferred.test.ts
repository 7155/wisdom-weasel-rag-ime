import { describe, expect, it } from 'vitest';
import { DeferredWorkQueue, defaultDeferredScheduler } from './starfield-deferred';

/** Manual scheduler: nothing runs until the test says so. */
function manualScheduler() {
  const pending = new Map<number, () => void>();
  let nextHandle = 1;
  return {
    scheduler: {
      schedule: (task: () => void) => {
        const handle = nextHandle;
        nextHandle += 1;
        pending.set(handle, task);
        return handle;
      },
      cancel: (handle: number) => {
        pending.delete(handle);
      },
    },
    /** Run every callback the queue has handed out so far. */
    flush(): number {
      let ran = 0;
      while (pending.size > 0) {
        const [handle, task] = [...pending][0]!;
        pending.delete(handle);
        task();
        ran += 1;
      }
      return ran;
    },
    get scheduled(): number {
      return pending.size;
    },
  };
}

describe('starfield deferred work', () => {
  it('runs queued upgrades in order, one callback at a time', () => {
    const host = manualScheduler();
    const queue = new DeferredWorkQueue(host.scheduler);
    const ran: string[] = [];
    queue.push(() => ran.push('sky'));
    queue.push(() => ran.push('center'));

    // Two tasks must not claim two idle callbacks up front: a burst of
    // upgrades running back to back would recreate the stall we avoided.
    expect(host.scheduled).toBe(1);
    expect(queue.pending).toBe(2);

    host.flush();
    expect(ran).toEqual(['sky', 'center']);
    expect(queue.pending).toBe(0);
  });

  it('drops everything still pending when the stage is torn down', () => {
    const host = manualScheduler();
    const queue = new DeferredWorkQueue(host.scheduler);
    let ran = 0;
    queue.push(() => { ran += 1; });
    queue.push(() => { ran += 1; });

    queue.cancelAll();

    expect(queue.pending).toBe(0);
    expect(host.scheduled).toBe(0);
    expect(host.flush()).toBe(0);
    expect(ran).toBe(0);
  });

  it('keeps draining after a task throws', () => {
    const host = manualScheduler();
    const queue = new DeferredWorkQueue(host.scheduler);
    const ran: string[] = [];
    queue.push(() => { throw new Error('texture upgrade failed'); });
    queue.push(() => ran.push('second'));

    expect(() => host.flush()).toThrow('texture upgrade failed');
    host.flush();

    expect(ran).toEqual(['second']);
    expect(queue.pending).toBe(0);
  });

  it('accepts new work after the queue has drained', () => {
    const host = manualScheduler();
    const queue = new DeferredWorkQueue(host.scheduler);
    const ran: string[] = [];
    queue.push(() => ran.push('first'));
    host.flush();
    queue.push(() => ran.push('second'));
    host.flush();
    expect(ran).toEqual(['first', 'second']);
  });

  it('falls back to a timeout when the host has no idle callback', () => {
    const host = globalThis as Record<string, unknown>;
    const savedRequest = host.requestIdleCallback;
    const savedCancel = host.cancelIdleCallback;
    delete host.requestIdleCallback;
    delete host.cancelIdleCallback;
    try {
      const scheduler = defaultDeferredScheduler();
      const handle = scheduler.schedule(() => undefined);
      expect(handle).toBeDefined();
      // Cancelling a timeout handle must not throw.
      expect(() => scheduler.cancel(handle)).not.toThrow();
    } finally {
      if (savedRequest) host.requestIdleCallback = savedRequest;
      if (savedCancel) host.cancelIdleCallback = savedCancel;
    }
  });
});
