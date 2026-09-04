import { describe, expect, it, vi } from 'vitest';

import { SseParser } from './sse';

describe('SseParser', () => {
  it('parses split CRLF chunks, comments, ids, and multiline data', () => {
    const events: unknown[] = [];
    const parser = new SseParser((event) => events.push(event));
    parser.push(': connected\r\nid: session-1:7\r\nevent: text_delta\r\nda');
    parser.push('ta: {"part":\r\ndata: "two"}\r\nretry: 25\r\n\r\n');
    parser.finish();
    expect(events).toEqual([
      {
        id: 'session-1:7',
        event: 'text_delta',
        data: '{"part":\n"two"}',
        retry: 25,
      },
    ]);
  });

  it('ignores heartbeat comments without emitting empty events', () => {
    const events: unknown[] = [];
    const parser = new SseParser((event) => events.push(event));
    parser.push(': heartbeat\n\n');
    parser.finish();
    expect(events).toEqual([]);
  });

  it('discards an event when the stream ends before its empty-line frame boundary', () => {
    const events: unknown[] = [];
    const parser = new SseParser((event) => events.push(event));
    parser.push('id: session-1:8\nevent: turn_completed\ndata: {"status":"completed"}');

    parser.finish();

    expect(events).toEqual([]);
  });

  it('reports a complete heartbeat comment as a stable SSE frame', () => {
    const onFrame = vi.fn();
    const parser = new SseParser(vi.fn(), onFrame);

    parser.push(': heartbeat\n\n');

    expect(onFrame).toHaveBeenCalledTimes(1);
  });
});
