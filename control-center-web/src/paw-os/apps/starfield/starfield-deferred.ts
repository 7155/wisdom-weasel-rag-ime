/**
 * 星空 deferred work — the escape hatch for expensive-but-not-urgent texture
 * synthesis.
 *
 * Opening the sky must not freeze the desktop. The full deep-sky dome costs
 * over a hundred milliseconds of synchronous noise evaluation, which is a
 * visible stall on the very click that is supposed to feel instant. So the
 * stage shows a cheap preview immediately and queues the expensive upgrade
 * here, to run once the browser is idle.
 *
 * The queue is deliberately tiny and renderer-free:
 *
 * - tasks run in submission order, one per idle callback, so a burst of
 *   upgrades never re-creates the stall it was meant to avoid;
 * - `cancelAll` drops everything still pending, so a disposed stage or a
 *   sky the user already left never pays for work nobody will see;
 * - the scheduler is injectable, which keeps the whole thing unit-testable
 *   in Node without `requestIdleCallback`.
 */

export type DeferredTask = () => void;

/** Runs `task` later and returns a handle that `cancel` understands. */
export type DeferredScheduler = (task: () => void) => number;
export type DeferredCanceller = (handle: number) => void;

interface IdleWindow {
  requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
  cancelIdleCallback?: (handle: number) => void;
}

/**
 * Idle scheduling when the browser offers it, otherwise a short timeout.
 * The timeout ceiling matters: an always-busy tab must still get its full
 * quality sky rather than waiting for an idle moment that never comes.
 */
export function defaultDeferredScheduler(): { schedule: DeferredScheduler; cancel: DeferredCanceller } {
  const host = globalThis as unknown as IdleWindow;
  if (typeof host.requestIdleCallback === 'function' && typeof host.cancelIdleCallback === 'function') {
    const request = host.requestIdleCallback.bind(host);
    const cancel = host.cancelIdleCallback.bind(host);
    return {
      schedule: (task) => request(task, { timeout: 600 }),
      cancel,
    };
  }
  return {
    schedule: (task) => setTimeout(task, 32) as unknown as number,
    cancel: (handle) => clearTimeout(handle),
  };
}

export class DeferredWorkQueue {
  private readonly queue: DeferredTask[] = [];
  private readonly schedule: DeferredScheduler;
  private readonly cancel: DeferredCanceller;
  private handle: number | null = null;

  constructor(scheduler?: { schedule: DeferredScheduler; cancel: DeferredCanceller }) {
    const resolved = scheduler ?? defaultDeferredScheduler();
    this.schedule = resolved.schedule;
    this.cancel = resolved.cancel;
  }

  get pending(): number {
    return this.queue.length;
  }

  push(task: DeferredTask): void {
    this.queue.push(task);
    this.pump();
  }

  cancelAll(): void {
    this.queue.length = 0;
    if (this.handle !== null) {
      this.cancel(this.handle);
      this.handle = null;
    }
  }

  private pump(): void {
    if (this.handle !== null || this.queue.length === 0) return;
    this.handle = this.schedule(() => {
      this.handle = null;
      const task = this.queue.shift();
      // A throwing upgrade must not strand the rest of the queue: the sky is
      // already on screen at preview quality, so failure is cosmetic.
      try {
        task?.();
      } finally {
        this.pump();
      }
    });
  }
}
