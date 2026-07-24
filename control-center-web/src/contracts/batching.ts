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

export function createEventBatcher<Event, Handle = ReturnType<typeof setTimeout>>(
  options: EventBatcherOptions<Event, Handle>,
): EventBatcher<Event> {
  const intervalMs = clamp(options.intervalMs ?? 20, 16, 33);
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
  intervalMs = 20,
): EventBatcher<UiRoomEvent> {
  return createEventBatcher({
    commit,
    intervalMs,
    isDelta: (event) => event.eventType === 'participant_delta',
  });
}

function defaultFrameScheduler(): BatchScheduler<number | ReturnType<typeof setTimeout>> {
  if (
    typeof globalThis.requestAnimationFrame === 'function'
    && typeof globalThis.cancelAnimationFrame === 'function'
  ) {
    return {
      schedule: (callback) => globalThis.requestAnimationFrame(callback),
      cancel: (handle) => globalThis.cancelAnimationFrame(handle as number),
    };
  }
  return {
    schedule: (callback, delayMs) => globalThis.setTimeout(callback, delayMs),
    cancel: (handle) => globalThis.clearTimeout(handle),
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
