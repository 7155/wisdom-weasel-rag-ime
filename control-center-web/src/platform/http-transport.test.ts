import { describe, expect, it, vi } from 'vitest';

import { agentEventFixture } from '@/test/fixtures/events';

import { HttpControlTransport } from './http-transport';

describe('HttpControlTransport', () => {
  it('uses a fixed route mapping rather than caller-provided URLs', async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return new Response(JSON.stringify({ ok: true }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }) as typeof fetch;
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8766',
      fetch: fetchMock,
    });

    await expect(transport.request({ pathId: 'system.health' })).resolves.toEqual({ ok: true });
    expect(calls[0]).toMatchObject({
      url: 'http://127.0.0.1:8766/api/health',
      init: { method: 'GET' },
    });
  });

  it('validates requested response contracts at the HTTP boundary', async () => {
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8766',
      fetch: vi.fn(async () => new Response(JSON.stringify({ id: 'missing-fields' }))) as typeof fetch,
    });
    await expect(
      transport.request({
        pathId: 'system.health',
        responseContract: 'agent-session.v1',
      }),
    ).rejects.toThrow(/Invalid agent-session.v1/);
  });

  it('reconnects SSE with the latest Last-Event-ID and validates envelopes', async () => {
    const headers: string[] = [];
    const payloads = [agentEventFixture(1, 'text_delta', { delta: 'A' }), agentEventFixture(2, 'turn_completed', {})];
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      headers.push(new Headers(init?.headers).get('Last-Event-ID') ?? '<missing>');
      const event = payloads.shift();
      return new Response(event ? sse(event) : ': heartbeat\n\n', {
        headers: { 'Content-Type': 'text/event-stream' },
      });
    });
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8766',
      fetch: fetchMock as typeof fetch,
      reconnectBaseDelayMs: 0,
      reconnectMaxDelayMs: 0,
      random: () => 0,
    });
    const received: string[] = [];
    let cancel = () => {};
    const done = new Promise<void>((resolve) => {
      cancel = transport.subscribe(
        {
          pathId: 'agent.session.events',
          params: { sessionId: 'session-1' },
          lastEventId: 'session-1:0',
        },
        {
          next(event) {
            const typed = event as ReturnType<typeof agentEventFixture>;
            received.push(typed.eventId);
            if (received.length === 2) {
              cancel();
              resolve();
            }
          },
        },
      );
    });
    await done;

    expect(received).toEqual(['session-1:1', 'session-1:2']);
    expect(headers.slice(0, 2)).toEqual(['session-1:0', 'session-1:1']);
    expect(fetchMock.mock.calls[1]?.[0].toString()).toContain('lastEventId=session-1%3A1');
  });

  it('aborts an in-flight request and cancels reconnect work', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        }),
    ) as typeof fetch;
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8766',
      fetch: fetchMock,
    });
    const controller = new AbortController();
    const pending = transport.request({ pathId: 'system.health', signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });
});

function sse(event: { eventId: string; eventType: string }): string {
  return `id: ${event.eventId}\nevent: ${event.eventType}\ndata: ${JSON.stringify(event)}\n\n`;
}
