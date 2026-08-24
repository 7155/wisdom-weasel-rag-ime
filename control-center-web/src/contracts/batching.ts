import type { UiAgentEvent, UiRoomEvent } from './ui-events';

export interface BatchScheduler<Handle = unknown> {
  schedule(callback: () => void, delayMs: number): Handle;
  cancel(handle: Handle): void;
}

export interface EventBatcher<Event> {
  push(event: Event): void;
  flush(): void;
  clear(): void;
  readonly pendingCount: number;
}

export interface EventBatcherOptions<Event, Handle = unknown> {
  commit(events: readonly Event[]): void;
  isDelta(event: Event): boolean;
  intervalMs?: number;
  scheduler?: BatchScheduler<Handle>;
}

type DefaultSchedulerHandle = {
  cancelled: boolean;
  timer?: ReturnType<typeof setTimeout>;
  frame?: number;
};

export function createEventBatcher<Event, Handle = DefaultSchedulerHandle>(
  options: EventBatcherOptions<Event, Handle>,
): EventBatcher<Event> {
  const intervalMs = clamp(options.intervalMs ?? 20, 16, 120);
  const scheduler =
    options.scheduler ??
    (defaultFrameScheduler() as unknown as BatchScheduler<Handle>);
  let pending: Event[] = [];
  let scheduled: Handle | undefined;

  const batcher: EventBatcher<Event> = {
    push(event) {
      if (!options.isDelta(event)) {
        batcher.flush();
        options.commit([event]);
        return;
      }
      pending.push(event);
      if (scheduled === undefined) {
        scheduled = scheduler.schedule(() => {
          scheduled = undefined;
          batcher.flush();
        }, intervalMs);
      }
    },
    flush() {
      if (scheduled !== undefined) {
        scheduler.cancel(scheduled);
        scheduled = undefined;
      }
      if (pending.length === 0) return;
      const events = pending;
      pending = [];
      options.commit(events);
    },
    clear() {
      if (scheduled !== undefined) scheduler.cancel(scheduled);
      scheduled = undefined;
      pending = [];
    },
    get pendingCount() {
      return pending.length;
    },
  };
  return batcher;
}

export function createAgentDeltaBatcher(
  commit: (events: readonly UiAgentEvent[]) => void,
  intervalMs = 20,
): EventBatcher<UiAgentEvent> {
  return createEventBatcher({
    commit,
    intervalMs,
    isDelta: (event) => event.eventType === 'text_delta',
  });
}

export function createRoomDeltaBatcher(
  commit: (events: readonly UiRoomEvent[]) => void,
  intervalMs = 80,
): EventBatcher<UiRoomEvent> {
  return createEventBatcher({
    commit,
    intervalMs,
    isDelta: (event) => event.eventType === 'participant_delta',
  });
}

function defaultFrameScheduler(): BatchScheduler<DefaultSchedulerHandle> {
  if (
    typeof globalThis.requestAnimationFrame === 'function'
    && typeof globalThis.cancelAnimationFrame === 'function'
  ) {
    return {
      schedule: (callback, delayMs) => {
        const handle: DefaultSchedulerHandle = { cancelled: false };
        // ProMotion displays can invoke requestAnimationFrame at 120 Hz. Wait
        // for the batching interval first, then publish on the next paint.
        handle.timer = globalThis.setTimeout(() => {
          handle.timer = undefined;
          if (handle.cancelled) return;
          handle.frame = globalThis.requestAnimationFrame(() => {
            handle.frame = undefined;
            if (!handle.cancelled) callback();
          });
        }, delayMs);
        return handle;
      },
      cancel: (handle) => {
        handle.cancelled = true;
        if (handle.timer !== undefined) globalThis.clearTimeout(handle.timer);
        if (handle.frame !== undefined) globalThis.cancelAnimationFrame(handle.frame);
      },
    };
  }
  return {
    schedule: (callback, delayMs) => {
      const handle: DefaultSchedulerHandle = { cancelled: false };
      handle.timer = globalThis.setTimeout(() => {
        handle.timer = undefined;
        if (!handle.cancelled) callback();
      }, delayMs);
      return handle;
    },
    cancel: (handle) => {
      handle.cancelled = true;
      if (handle.timer !== undefined) globalThis.clearTimeout(handle.timer);
    },
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
