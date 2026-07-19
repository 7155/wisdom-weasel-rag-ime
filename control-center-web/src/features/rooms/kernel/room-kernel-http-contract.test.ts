import { describe, expect, it, vi } from 'vitest';
import type { RoomEventEnvelopeV2 } from '@/contracts/generated/room-event-envelope.v2';
import { HttpControlTransport } from '@/platform/http-transport';

describe('Room Kernel HTTP and SSE contracts', () => {
  it('uses the fixed snapshot route and does not accept a caller URL', async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(snapshot()), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }));
    const transport = new HttpControlTransport({ baseUrl: 'http://127.0.0.1:8766', fetch: fetcher as typeof fetch });
    await expect(transport.request({
      pathId: 'agent.room.kernel.snapshot', params: { roomId: 'room:a' },
    })).resolves.toMatchObject({ roomId: 'room:a', lastSequence: 1 });
    expect(String(fetcher.mock.calls[0]?.[0])).toBe('http://127.0.0.1:8766/api/agent/rooms/room%3Aa/kernel/snapshot');
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ method: 'GET' });
  });

  it('resumes the fixed SSE stream with Last-Event-ID and preserves canonical sequence', async () => {
    const event = rootEvent(2);
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(
      `id: room-a#2\nevent: room_kernel_event\ndata: ${JSON.stringify(event)}\n\n`,
      { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
    ));
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8766', fetch: fetcher as typeof fetch,
      reconnectBaseDelayMs: 10_000, reconnectMaxDelayMs: 10_000,
    });
    let stop = () => {};
    const received = new Promise<unknown>((resolve, reject) => {
      stop = transport.subscribe(
        { pathId: 'agent.room.kernel.events', params: { roomId: 'room-a' }, lastEventId: 'room-a#1' },
        { next: resolve, error: reject },
      );
    });
    await expect(received).resolves.toEqual(event);
    stop();
    expect(String(fetcher.mock.calls[0]?.[0])).toContain('/api/agent/rooms/room-a/kernel/events?lastEventId=room-a%231');
    const headers = fetcher.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get('Last-Event-ID')).toBe('room-a#1');
  });
});

function snapshot() {
  return { roomId: 'room:a', lastSequence: 1, snapshotHash: `sha256:${'a'.repeat(64)}`, roots: [], tasks: [], dispatches: [], posts: [], sessions: [], receipts: [] };
}

function rootEvent(sequence: number): RoomEventEnvelopeV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-event-envelope.v2', entityKind: 'root', entityId: 'root-a',
    eventKind: 'state_changed', sequence, occurredAtMs: sequence, payload: { root: {} },
  };
}
