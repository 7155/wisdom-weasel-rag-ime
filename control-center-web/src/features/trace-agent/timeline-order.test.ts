import { describe, expect, it } from 'vitest';
import { orderTraceTimelineEntries, recordedTimelineSequence, type TraceTimelineOrderEntry } from './timeline-order';

describe('Trace timeline order', () => {
  it('never treats epoch timestamps as recorded ordinals', () => {
    expect(recordedTimelineSequence({ createdAtMs: 1788324850227 })).toBeUndefined();
    expect(recordedTimelineSequence({ timelineSequence: 2.9, sequence: 74, createdAtMs: 1788324854774 })).toBe(2.9);
    expect(recordedTimelineSequence({ sequence: 4, createdAtMs: 1788325221761 })).toBe(4);
  });

  it('keeps recorded order through clock regressions and anchors later user messages within their own turn', () => {
    const entries: TraceTimelineOrderEntry[] = [
      { id: 'user-1', kind: 'user', turnId: 'turn-1', messageIndex: 0, createdAtMs: 10 },
      { id: 'reasoning-1', kind: 'reasoning', turnId: 'turn-1', sequence: 2.1, createdAtMs: 30 },
      { id: 'assistant-1', kind: 'assistant', turnId: 'turn-1', messageIndex: 1, sequence: 2.9, createdAtMs: 20 },
      { id: 'steer-1', kind: 'user', turnId: 'turn-1', messageIndex: 2, createdAtMs: 40 },
      { id: 'reasoning-2', kind: 'reasoning', turnId: 'turn-1', sequence: 4.1, createdAtMs: 35 },
      { id: 'assistant-2', kind: 'assistant', turnId: 'turn-1', messageIndex: 3, sequence: 6.9, createdAtMs: 36 },
      { id: 'user-2', kind: 'user', turnId: 'turn-2', messageIndex: 4, createdAtMs: 50 },
      { id: 'assistant-3', kind: 'assistant', turnId: 'turn-2', messageIndex: 5, sequence: 8.9, createdAtMs: 45 },
    ];
    const expected = entries.map(({ id }) => id);
    for (let offset = 0; offset < entries.length; offset += 1) {
      const permutation = [...entries.slice(offset), ...entries.slice(0, offset)];
      expect(orderTraceTimelineEntries(permutation).map(({ id }) => id)).toEqual(expected);
      expect(orderTraceTimelineEntries(permutation.reverse()).map(({ id }) => id)).toEqual(expected);
    }
    expect(entries[0].sequence).toBeUndefined();
  });

  it('uses chronological fallback when the source contains no recorded ordinals', () => {
    const entries: TraceTimelineOrderEntry[] = [
      { id: 'assistant', kind: 'assistant', messageIndex: 1, createdAtMs: 20 },
      { id: 'tool', kind: 'tool_finished', createdAtMs: 15 },
      { id: 'user', kind: 'user', messageIndex: 0, createdAtMs: 10 },
    ];
    expect(orderTraceTimelineEntries(entries).map(({ id }) => id)).toEqual(['user', 'tool', 'assistant']);
  });
});
