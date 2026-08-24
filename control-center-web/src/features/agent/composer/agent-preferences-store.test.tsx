import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { PropsWithChildren } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import {
  type AgentPreferences,
  useAgentPreferences,
  useAgentPreferencesAuthority,
} from './agent-preferences-store';

const payloadSha256 = 'c'.repeat(64);

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe('Agent preference configuration authority', () => {
  it('reads typed preferences from configuration.settings and ignores stale browser storage', async () => {
    window.localStorage.setItem('pawos:agent:preferences', JSON.stringify({
      modelReference: 'stale/local-model',
      thinking: 'low',
      executionMode: 'full_trust',
    }));
    const transport = preferenceTransport({
      modelReference: 'openai-codex/gpt-5.6-terra',
      thinking: 'high',
      executionMode: 'read_only',
    });
    const { result } = renderHook(() => useAgentPreferences(), { wrapper: wrapper(transport) });

    await waitFor(() => expect(result.current).toEqual({
      modelReference: 'openai-codex/gpt-5.6-terra',
      thinking: 'high',
      executionMode: 'read_only',
    }));
    expect(transport.requests.some(({ request }) => request.pathId === 'configuration.settings')).toBe(true);
  });

  it('previews, applies, and re-reads a successful write through the same authority', async () => {
    let persisted = defaults();
    let settingsReads = 0;
    const transport = preferenceTransport(persisted, {
      onRead: () => { settingsReads += 1; return persisted; },
      onApply: (changes) => {
        persisted = {
          modelReference: String(changes['agent.defaults.modelReference']),
          thinking: String(changes['agent.defaults.thinkingLevel']),
          executionMode: String(changes['agent.defaults.executionMode']) as typeof persisted.executionMode,
        };
      },
    });
    const { result } = renderHook(() => useAgentPreferencesAuthority(), { wrapper: wrapper(transport) });
    await waitFor(() => expect(result.current.isPending).toBe(false));

    await act(async () => {
      await result.current.save({
        modelReference: 'openai-codex/gpt-5.6-sol',
        thinking: 'max',
        executionMode: 'workspace_managed',
      });
    });

    expect(requestFor(transport, 'configuration.settings.preview')?.body).toEqual({
      changes: {
        'agent.defaults.modelReference': 'openai-codex/gpt-5.6-sol',
        'agent.defaults.thinkingLevel': 'max',
        'agent.defaults.executionMode': 'workspace_managed',
      },
      expectedRuntimeRevision: 7,
    });
    expect(requestFor(transport, 'configuration.settings.apply')?.body).toMatchObject({
      previewToken: 'agent-defaults-preview',
      payloadSha256,
      confirmText: 'apply',
    });
    expect(settingsReads).toBeGreaterThanOrEqual(2);
    expect(result.current.preferences).toEqual(persisted);
    expect(result.current.saveError).toBe('');
  });

  it('rolls back optimistic state and exposes recovery when the authority rejects a write', async () => {
    const persisted = defaults();
    const transport = preferenceTransport(persisted, { failApply: true });
    const { result } = renderHook(() => useAgentPreferencesAuthority(), { wrapper: wrapper(transport) });
    await waitFor(() => expect(result.current.isPending).toBe(false));

    await act(async () => {
      await result.current.save({ executionMode: 'full_trust' });
    });

    expect(result.current.preferences).toEqual(persisted);
    expect(result.current.saveError).toContain('重新读取');
    expect(window.localStorage.getItem('pawos:agent:preferences')).toBeNull();
  });

  it('reopens from persisted configuration instead of retaining a module or browser copy', async () => {
    let persisted = defaults();
    const transport = preferenceTransport(persisted, {
      onRead: () => persisted,
      onApply: (changes) => {
        persisted = { ...persisted, executionMode: String(changes['agent.defaults.executionMode']) as typeof persisted.executionMode };
      },
    });
    const first = renderHook(() => useAgentPreferencesAuthority(), { wrapper: wrapper(transport) });
    await waitFor(() => expect(first.result.current.isPending).toBe(false));
    await act(async () => { await first.result.current.save({ executionMode: 'read_only' }); });
    first.unmount();

    window.localStorage.setItem('pawos:agent:preferences', JSON.stringify({ executionMode: 'full_trust' }));
    const reopened = renderHook(() => useAgentPreferences(), { wrapper: wrapper(transport) });
    await waitFor(() => expect(reopened.result.current.executionMode).toBe('read_only'));
  });
});

function wrapper(transport: MockControlTransport) {
  return function PreferenceProviders({ children }: PropsWithChildren) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    return (
      <QueryClientProvider client={client}>
        <ControlTransportProvider transport={transport}>{children}</ControlTransportProvider>
      </QueryClientProvider>
    );
  };
}

function defaults(): AgentPreferences {
  return {
    modelReference: '',
    thinking: 'high',
    executionMode: 'per_action',
  };
}

function preferenceTransport(
  initial: ReturnType<typeof defaults>,
  options: {
    failApply?: boolean;
    onApply?: (changes: Record<string, unknown>) => void;
    onRead?: () => ReturnType<typeof defaults>;
  } = {},
) {
  return new MockControlTransport({
    capabilities: {
      features: { managementWorkContract: true, configurationSettingsWorkContract: true },
    },
    routes: {
      'configuration.settings': () => settingsPayload(options.onRead?.() ?? initial),
      'configuration.settings.preview': {
        schemaVersion: 'rag-ime.management-work-preview.v1',
        ok: true,
        previewToken: 'agent-defaults-preview',
        pathId: 'configuration.settings.apply',
        payloadSha256,
        expectedRevision: { runtimeRevision: 7, subjectRevision: 'settings:7' },
        expiresAtMs: Date.now() + 60_000,
        requiredConfirm: 'apply',
        summary: { title: '保存 Agent 默认设置', items: ['更新新建 Session 的默认值'], risk: 'R1' },
      },
      'configuration.settings.apply': (request: ControlRequest) => {
        if (options.failApply) throw new Error('本机设置发生变化，请重新读取后重试。');
        const changes = (request.body as Record<string, unknown>).changes as Record<string, unknown>;
        options.onApply?.(changes);
        return {
          schemaVersion: 'rag-ime.management-work-receipt.v1',
          ok: true,
          receiptId: 'agent-defaults-receipt',
          pathId: 'configuration.settings.apply',
          payloadSha256,
          appliedAtMs: Date.now(),
          rollbackAvailable: true,
          rollbackToken: 'agent-defaults-rollback',
        };
      },
    },
  });
}

function settingsPayload(preferences: ReturnType<typeof defaults>) {
  return {
    ok: true,
    settings: {
      agent: {
        defaults: {
          modelReference: preferences.modelReference || 'inherit',
          thinkingLevel: preferences.thinking,
          executionMode: preferences.executionMode,
        },
      },
    },
    runtimeConfig: { runtimeRevision: 7 },
  };
}

function requestFor(transport: MockControlTransport, pathId: string) {
  return transport.requests.find(({ request }) => request.pathId === pathId)?.request;
}
