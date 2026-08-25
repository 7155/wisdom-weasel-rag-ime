import { describe, expect, it, vi } from 'vitest';
import {
  createChatPerformanceMarker,
  measureAgentChatOperation,
  messageLengthBucket,
  observeAgentChatLongTasks,
  performanceMarkTelemetrySink,
} from './telemetry';

describe('agent chat telemetry', () => {
  it('buckets message lengths without retaining the text', () => {
    expect(messageLengthBucket(0)).toBe('<1k');
    expect(messageLengthBucket(999)).toBe('<1k');
    expect(messageLengthBucket(1_000)).toBe('1k-10k');
    expect(messageLengthBucket(10_000)).toBe('10k-50k');
    expect(messageLengthBucket(50_000)).toBe('50k-100k');
    expect(messageLengthBucket(100_000)).toBe('100k+');
  });

  it('measures a sync operation into a content-free sample', () => {
    const sink = vi.fn();
    const result = measureAgentChatOperation(
      'agent-chat.reveal-tick',
      { lengthBucket: messageLengthBucket(2_400) },
      () => 42,
      sink,
    );
    expect(result).toBe(42);
    expect(sink).toHaveBeenCalledOnce();
    expect(sink.mock.calls[0]?.[0]).toMatchObject({
      name: 'agent-chat.reveal-tick',
      fields: { lengthBucket: '1k-10k' },
    });
    expect(typeof sink.mock.calls[0]?.[0].durationMs).toBe('number');
  });

  it('records Performance marks through the marker helper', () => {
    const sink = vi.fn();
    const marker = createChatPerformanceMarker(sink);
    marker.mark('agent-chat.first-delta');
    marker.mark('agent-chat.first-paint');
    const sample = marker.measure(
      'agent-chat.first-paint-latency',
      'agent-chat.first-delta',
      'agent-chat.first-paint',
      { lengthBucket: '<1k' },
    );
    expect(sample?.name).toBe('agent-chat.first-paint-latency');
    expect(sink).toHaveBeenCalled();
  });

  it('keeps the default sink field-free (mark name only)', () => {
    expect(() => performanceMarkTelemetrySink({
      name: 'agent-chat.follow-detach',
      durationMs: 1,
      fields: { reason: 'selection' },
    })).not.toThrow();
  });

  it('returns a disconnectable handle even when longtask is unsupported', () => {
    const handle = observeAgentChatLongTasks(() => undefined, { surface: 'timeline' });
    expect(() => handle.disconnect()).not.toThrow();
  });
});
