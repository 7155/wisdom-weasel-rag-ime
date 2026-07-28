import { describe, expect, it, vi } from 'vitest';

import { agentEventFixture } from '@/test/fixtures/events';

import {
  ControlTransportHttpError,
  HttpControlTransport,
} from './http-transport';

describe('HttpControlTransport', () => {
  it('resolves browser snapshot images against the configured HTTP origin', () => {
    const transport = new HttpControlTransport({
      baseUrl: 'https://gateway.example.test/control/',
      fetch: vi.fn() as typeof fetch,
    });

    expect(transport.browserSnapshotImageUrl('snap_remote-1')).toBe(
      'https://gateway.example.test/api/browser/snapshots/snap_remote-1/image',
    );
    expect(() => transport.browserSnapshotImageUrl('../private')).toThrow(/bounded snapshotId/);
  });

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

  it('marks bodyless delete requests as JSON management writes', async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return new Response(JSON.stringify({ ok: true }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }) as typeof fetch;
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8768',
      fetch: fetchMock,
    });

    await transport.request({
      pathId: 'agent.session.delete',
      params: { sessionId: 'agent:test-delete' },
    });

    expect(calls[0]?.url).toBe('http://127.0.0.1:8768/api/agent/sessions/agent%3Atest-delete');
    expect(calls[0]?.init?.method).toBe('DELETE');
    expect(calls[0]?.init?.body).toBeUndefined();
    expect(new Headers(calls[0]?.init?.headers).get('Content-Type')).toBe('application/json');
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

  it('preserves typed command receipt payloads on HTTP errors', async () => {
    const payload = {
      ok: false,
      code: 'AGENT_COMMAND_PENDING',
      error: 'still pending',
      commandReceipt: {
        state: 'pending',
        clientMessageId: 'client-1',
      },
    };
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8766',
      fetch: vi.fn(async () => new Response(
        JSON.stringify(payload),
        {
          status: 409,
          headers: { 'Content-Type': 'application/json' },
        },
      )) as typeof fetch,
    });

    await expect(transport.request({
      pathId: 'agent.session.prompt',
      params: { sessionId: 'session-1' },
      body: {
        message: 'hello',
        clientMessageId: 'client-1',
      },
    })).rejects.toMatchObject({
      status: 409,
      payload,
    } satisfies Partial<ControlTransportHttpError>);
  });

  it('falls back to the fixed 8766 route catalog when the facade is not mounted yet', async () => {
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8766',
      fetch: vi.fn(async () => new Response('not found', { status: 404 })) as typeof fetch,
    });

    await expect(transport.capabilities()).resolves.toMatchObject({
      transport: 'http',
      features: { legacyEndpointAdapter: true },
    });
  });

  it('streams browser-selected knowledge files only to the fixed kb import route', async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const file = new File(['manual'], 'manual.pdf', { type: 'application/pdf' });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return new Response(JSON.stringify({
        schemaVersion: 'rag-ime.knowledge-document-import.v1',
        ok: true,
        receipt: {
          kbId: 'kb_docs',
          documentId: 'doc_manual_01',
          fileName: 'manual.pdf',
          mimeType: 'application/pdf',
          byteSize: file.size,
          sha256: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
          status: 'queued',
        },
      }), { status: 201, headers: { 'Content-Type': 'application/json' } });
    }) as typeof fetch;
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8766',
      fetch: fetchMock,
    });

    await expect(transport.importKnowledgeDocuments({
      kbId: 'kb_docs',
      files: [file],
      parserProvider: 'auto',
    })).resolves.toEqual([expect.objectContaining({ documentId: 'doc_manual_01' })]);
    expect(calls[0]?.url).toBe(
      'http://127.0.0.1:8766/api/knowledge-bases/kb_docs/documents/import?fileName=manual.pdf&mimeType=application%2Fpdf&parserProvider=auto',
    );
    expect(calls[0]?.init?.body).toBe(file);
    expect(new Headers(calls[0]?.init?.headers).get('Content-Type')).toBe('application/pdf');
  });

  it('reads a bounded knowledge image only from the fixed three-id asset route', async () => {
    const bytes = new Uint8Array([137, 80, 78, 71]);
    const assetId = await sha256(bytes);
    const calls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return new Response(bytes, {
        headers: {
          'Content-Type': 'image/png',
          'Content-Length': String(bytes.byteLength),
          ETag: `"${assetId}"`,
          'X-Content-Type-Options': 'nosniff',
          'Content-Disposition': 'inline; filename="asset.png"',
        },
      });
    }) as typeof fetch;
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8766',
      fetch: fetchMock,
    });

    await expect(transport.readKnowledgeAsset({
      kbId: 'kb_docs',
      fileId: 'file_manual',
      assetId,
    })).resolves.toMatchObject({
      kbId: 'kb_docs',
      fileId: 'file_manual',
      assetId,
      mimeType: 'image/png',
      byteSize: bytes.byteLength,
    });
    expect(calls).toEqual([
      `http://127.0.0.1:8766/api/knowledge-bases/kb_docs/documents/file_manual/assets/${assetId}`,
    ]);
    await expect(transport.readKnowledgeAsset({
      kbId: 'kb_docs',
      fileId: 'file_manual',
      assetId: '../private',
    })).rejects.toThrow(/sha256 assetId/);
    expect(calls).toHaveLength(1);
  });

  it('reads an original document only from the fixed two-id source route', async () => {
    const bytes = new TextEncoder().encode('%PDF-source');
    const sha = await sha256(bytes);
    const calls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return new Response(bytes, {
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Length': String(bytes.byteLength),
          ETag: `"${sha}"`,
          'X-Content-Type-Options': 'nosniff',
          'Content-Disposition': 'inline; filename="manual.pdf"',
        },
      });
    }) as typeof fetch;
    const transport = new HttpControlTransport({
      baseUrl: 'http://127.0.0.1:8766',
      fetch: fetchMock,
    });

    await expect(transport.readKnowledgeDocumentSource({
      kbId: 'kb_docs',
      fileId: 'file_manual',
    })).resolves.toMatchObject({
      kbId: 'kb_docs',
      fileId: 'file_manual',
      mimeType: 'application/pdf',
      byteSize: bytes.byteLength,
      sha256: sha,
    });
    expect(calls).toEqual([
      'http://127.0.0.1:8766/api/knowledge-bases/kb_docs/documents/file_manual/source',
    ]);
    await expect(transport.readKnowledgeDocumentSource({
      kbId: 'kb_docs',
      fileId: 'file_manual',
      path: '/Users/private/manual.pdf',
    } as never)).rejects.toThrow(/unsupported field/);
    expect(calls).toHaveLength(1);
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

async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', Uint8Array.from(bytes).buffer);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('');
}
