/**
 * Content-free performance instrumentation for the Agent transcript.
 *
 * Every sample here is a name, a duration and a bounded set of enum or bucket
 * fields. Nothing carries prompt text, message bodies, file paths or Session
 * identifiers, and the default sink deliberately drops the fields entirely: it
 * writes a `performance.mark` and nothing else, so instrumentation added in
 * passing cannot become an exfiltration path. A host that wants the fields has
 * to install its own sink and take responsibility for where they go.
 *
 * Vendored from `paw-agent-chat-ui-kit` (`src/core/performance/telemetry.ts`,
 * MIT); see `ATTRIBUTION.md`.
 */

export interface AgentChatPerformanceSample {
  readonly name: string;
  readonly durationMs: number;
  readonly fields: Readonly<Record<string, string | number | boolean | null>>;
}

export type AgentChatTelemetrySink = (sample: AgentChatPerformanceSample) => void;

export const noopAgentChatTelemetrySink: AgentChatTelemetrySink = () => {};

/** The default: a name on the performance timeline, never a field value. */
export const performanceMarkTelemetrySink: AgentChatTelemetrySink = (sample) => {
  if (typeof performance === 'undefined' || typeof performance.mark !== 'function') return;
  try {
    performance.mark(sample.name);
  } catch {
    // A saturated or unavailable performance buffer must never break a render.
  }
};

export function measureAgentChatOperation<T>(
  name: string,
  fields: AgentChatPerformanceSample['fields'],
  operation: () => T,
  sink: AgentChatTelemetrySink = performanceMarkTelemetrySink,
): T {
  const start = monotonicNow();
  try {
    return operation();
  } finally {
    sink({ name, durationMs: monotonicNow() - start, fields });
  }
}

export async function measureAgentChatOperationAsync<T>(
  name: string,
  fields: AgentChatPerformanceSample['fields'],
  operation: () => Promise<T>,
  sink: AgentChatTelemetrySink = performanceMarkTelemetrySink,
): Promise<T> {
  const start = monotonicNow();
  try {
    return await operation();
  } finally {
    sink({ name, durationMs: monotonicNow() - start, fields });
  }
}

export interface ChatPerformanceMarker {
  mark(name: string): void;
  measure(
    name: string,
    startMark: string,
    endMark: string,
    fields?: AgentChatPerformanceSample['fields'],
  ): AgentChatPerformanceSample | null;
}

export function createChatPerformanceMarker(
  sink: AgentChatTelemetrySink = performanceMarkTelemetrySink,
): ChatPerformanceMarker {
  return {
    mark(name) {
      if (typeof performance === 'undefined' || typeof performance.mark !== 'function') return;
      try {
        performance.mark(name);
      } catch {
        // See performanceMarkTelemetrySink.
      }
    },
    measure(name, startMark, endMark, fields = {}) {
      if (typeof performance === 'undefined' || typeof performance.measure !== 'function') {
        return null;
      }
      try {
        performance.measure(name, startMark, endMark);
        const entry = performance.getEntriesByName(name, 'measure').at(-1);
        if (!entry) return null;
        const sample = { name, durationMs: entry.duration, fields };
        sink(sample);
        return sample;
      } catch {
        return null;
      }
    },
  };
}

export interface LongTaskObserverHandle {
  disconnect(): void;
}

/** Browser-only optional diagnostic. Unsupported engines return a no-op. */
export function observeAgentChatLongTasks(
  sink: AgentChatTelemetrySink = performanceMarkTelemetrySink,
  fields: AgentChatPerformanceSample['fields'] = {},
): LongTaskObserverHandle {
  if (
    typeof PerformanceObserver === 'undefined'
    || !PerformanceObserver.supportedEntryTypes?.includes('longtask')
  ) {
    return { disconnect() {} };
  }
  const observer = new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      sink({ name: 'agent-chat.long-task', durationMs: entry.duration, fields });
    }
  });
  observer.observe({ entryTypes: ['longtask'] });
  return { disconnect: () => observer.disconnect() };
}

/** Message size as a bucket, so a length can be reported without reporting a
 *  length precise enough to fingerprint one message. */
export function messageLengthBucket(length: number): string {
  if (length < 1_000) return '<1k';
  if (length < 10_000) return '1k-10k';
  if (length < 50_000) return '10k-50k';
  if (length < 100_000) return '50k-100k';
  return '100k+';
}

function monotonicNow(): number {
  return typeof performance === 'undefined' ? Date.now() : performance.now();
}
