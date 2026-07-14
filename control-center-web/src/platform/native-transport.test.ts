import { describe, expect, it, vi } from 'vitest';

import sessionFixture from '../../../tests/fixtures/agent/agent-session.json';

import type {
  NativeBridgeOutboundEnvelope,
  NativeBridgeRequestEnvelope,
} from './native-bridge';
import { NativeControlTransport } from './native-transport';
import { agentEventFixture } from '@/test/fixtures/events';

describe('NativeControlTransport', () => {
  it('matches the fixed WKWebView bridge envelope and validates results', async () => {
    const sent: NativeBridgeRequestEnvelope[] = [];
    let nextId = 1;
    const bridgeWindow = fakeBridgeWindow((envelope) => {
      sent.push(envelope);
      queueMicrotask(() => {
        bridgeWindow.__RAG_IME_NATIVE_BRIDGE__?.receive({
          id: envelope.id,
          ok: true,
          result:
            envelope.method === 'capabilities'
              ? capabilitiesFixture()
              : envelope.method === 'request'
                ? sessionFixture
                : {},
        });
      });
    });
    const transport = new NativeControlTransport({
      bridgeWindow,
      createId: () => `bridge-${nextId++}`,
    });

    const capabilities = await transport.capabilities();
    expect(capabilities).toMatchObject({
      transport: 'native',
      native: { pickFiles: true, revealPath: true, keychain: true, tcc: true },
    });
    await expect(
      transport.request({
        pathId: 'system.health',
        responseContract: 'agent-session.v1',
      }),
    ).resolves.toMatchObject({ id: 'agent-session-1' });

    expect(sent[0]).toEqual({ id: 'bridge-1', method: 'capabilities', payload: {} });
    expect(sent[1]).toEqual({
      id: 'bridge-2',
      method: 'request',
      payload: { pathId: 'system.health' },
    });
    expect(JSON.stringify(sent[1])).not.toMatch(/url|host|responseContract/);
    transport.dispose();
  });

  it('multiplexes subscribe/event/cancelSubscription with resume cursors', async () => {
    const sent: NativeBridgeRequestEnvelope[] = [];
    let nextId = 1;
    const bridgeWindow = fakeBridgeWindow((envelope) => {
      sent.push(envelope);
      queueMicrotask(() => {
        bridgeWindow.__RAG_IME_NATIVE_BRIDGE__?.receive({
          id: envelope.id,
          ok: true,
          result: {},
        });
      });
    });
    const transport = new NativeControlTransport({
      bridgeWindow,
      createId: () => `native-${nextId++}`,
    });
    const events: unknown[] = [];
    const cancel = transport.subscribe(
      {
        pathId: 'agent.session.events',
        params: { sessionId: 'session-1' },
        lastEventId: 'session-1:8',
      },
      { next: (event) => events.push(event) },
    );
    await Promise.resolve();
    const subscribe = sent.find((item) => item.method === 'subscribe');
    expect(subscribe?.payload).toEqual({
      subscriptionId: 'native-1',
      request: {
        pathId: 'agent.session.events',
        params: { sessionId: 'session-1' },
        lastEventId: 'session-1:8',
      },
    });

    const outbound: NativeBridgeOutboundEnvelope = {
      subscriptionId: 'native-1',
      kind: 'event',
      event: agentEventFixture(9, 'turn_completed', {}),
      lastEventId: 'session-1:9',
    };
    bridgeWindow.__RAG_IME_NATIVE_BRIDGE__?.receive(outbound);
    expect(events).toHaveLength(1);
    cancel();
    await Promise.resolve();
    expect(sent.find((item) => item.method === 'cancelSubscription')?.payload).toEqual({
      subscriptionId: 'native-1',
      lastEventId: 'session-1:9',
    });
    transport.dispose();
  });

  it('reconnects a completed native stream from the last acknowledged cursor', async () => {
    vi.useFakeTimers();
    try {
      const sent: NativeBridgeRequestEnvelope[] = [];
      let nextId = 1;
      const bridgeWindow = fakeBridgeWindow((envelope) => {
        sent.push(envelope);
        queueMicrotask(() => {
          bridgeWindow.__RAG_IME_NATIVE_BRIDGE__?.receive({
            id: envelope.id,
            ok: true,
            result: {},
          });
        });
      });
      const reconnects: unknown[] = [];
      const transport = new NativeControlTransport({
        bridgeWindow,
        createId: () => `resume-${nextId++}`,
      });
      const cancel = transport.subscribe(
        {
          pathId: 'agent.session.events',
          params: { sessionId: 'session-1' },
          lastEventId: 'session-1:8',
        },
        {
          next: () => undefined,
          reconnect: (state) => reconnects.push(state),
        },
      );
      await Promise.resolve();

      bridgeWindow.__RAG_IME_NATIVE_BRIDGE__?.receive({
        subscriptionId: 'resume-1',
        kind: 'complete',
        lastEventId: 'session-1:12',
      });
      expect(reconnects).toEqual([
        { attempt: 1, delayMs: 250, lastEventId: 'session-1:12' },
      ]);

      await vi.advanceTimersByTimeAsync(250);
      const subscribeCalls = sent.filter((item) => item.method === 'subscribe');
      expect(subscribeCalls).toHaveLength(2);
      expect(subscribeCalls[1]?.payload).toEqual({
        subscriptionId: 'resume-1',
        request: {
          pathId: 'agent.session.events',
          params: { sessionId: 'session-1' },
          lastEventId: 'session-1:12',
        },
      });
      cancel();
      await Promise.resolve();
      transport.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it('fails closed before posting an unknown pathId or arbitrary URL field', async () => {
    const sent: NativeBridgeRequestEnvelope[] = [];
    const bridgeWindow = fakeBridgeWindow((envelope) => sent.push(envelope));
    const transport = new NativeControlTransport({ bridgeWindow });
    await expect(
      transport.request({ pathId: 'system.openUrl' } as never),
    ).rejects.toThrow(/not allowlisted/);
    await expect(
      transport.request({ pathId: 'system.health', host: 'evil.invalid' } as never),
    ).rejects.toThrow(/host/);
    expect(sent).toEqual([]);
    transport.dispose();
  });
});

function fakeBridgeWindow(
  postMessage: (envelope: NativeBridgeRequestEnvelope) => void,
): Window {
  return {
    webkit: { messageHandlers: { ragImeNativeBridge: { postMessage } } },
  } as unknown as Window;
}

function capabilitiesFixture() {
  return {
    schemaVersion: 'rag-ime.control-capabilities.v1',
    features: { subscriptions: true },
    native: {
      filePicker: true,
      revealPath: true,
      keychainStatus: true,
      tccStatus: true,
      approvedExternalActions: true,
    },
    routes: [{ pathId: 'agent.session.events' }, { pathId: 'system.health' }],
  };
}
