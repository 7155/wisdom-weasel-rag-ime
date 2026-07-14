import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { HttpControlTransport } from '@/platform/http-transport';
import { NativeBridgeUnavailableError, NativeControlTransport } from '@/platform/native-transport';
import { CONTROL_ROUTES, controlRoute, type ControlPathId } from '@/platform/routes';
import type { ControlTransport } from '@/platform/transport';
import { MockControlTransport, type MockRouteHandler } from '@/test/mock-transport';

const ControlTransportContext = createContext<ControlTransport | null>(null);

export function ControlTransportProvider({
  children,
  transport,
}: {
  children: ReactNode;
  transport?: ControlTransport;
}) {
  const value = useMemo(() => transport ?? createConfiguredControlTransport(), [transport]);
  return (
    <ControlTransportContext.Provider value={value}>
      {children}
    </ControlTransportContext.Provider>
  );
}

export function useControlTransport(): ControlTransport {
  const transport = useContext(ControlTransportContext);
  if (!transport) {
    throw new Error('useControlTransport must be used inside ControlTransportProvider');
  }
  return transport;
}

export function createConfiguredControlTransport(): ControlTransport {
  const requested = import.meta.env.VITE_CONTROL_TRANSPORT ?? detectTransport();
  if (requested === 'native') {
    try {
      return new NativeControlTransport();
    } catch (error) {
      if (!(error instanceof NativeBridgeUnavailableError)) throw error;
    }
  }
  if (requested === 'http') {
    return new HttpControlTransport({
      baseUrl: import.meta.env.VITE_CONTROL_BASE_URL ?? 'http://127.0.0.1:8766',
    });
  }
  return createPreviewTransport();
}

function detectTransport(): 'native' | 'http' | 'mock' {
  if (window.webkit?.messageHandlers?.ragImeNativeBridge) return 'native';
  return import.meta.env.DEV ? 'mock' : 'http';
}

function createPreviewTransport(): MockControlTransport {
  const routes = Object.fromEntries(
    (Object.keys(CONTROL_ROUTES) as ControlPathId[])
      .filter((pathId) => !controlRoute(pathId).subscription)
      .map((pathId) => [pathId, previewResponse(pathId)]),
  ) as Partial<Record<ControlPathId, MockRouteHandler>>;
  return new MockControlTransport({
    routes,
    pickedFiles: [
      {
        id: 'media_preview_attachment_01',
        name: 'agent-runtime.png',
        mimeType: 'image/png',
        byteSize: 2_048,
        sessionId: 'session-preview',
        sha256: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
      },
    ],
  });
}

function previewResponse(pathId: ControlPathId): unknown {
  switch (pathId) {
    case 'agent.runtime.get':
      return {
        schemaVersion: 'rag-ime.agent-runtime.v1',
        enabled: true,
        managed: true,
        status: 'ready',
        driverId: 'pi-managed',
        runtimeKind: 'pi',
        runtimeVersion: 'preview',
        piVersion: 'preview',
        idleTimeoutSeconds: 900,
        activeSessionId: 'session-preview',
        lastError: '',
        capabilities: {},
      };
    case 'agent.session.models':
      return {
        schemaVersion: 'rag-ime.agent-model-catalog.v1',
        ok: true,
        sessionId: 'session-preview',
        selected: { provider: 'openai', modelId: 'gpt-5.4' },
        thinkingLevel: 'medium',
        providers: [
          {
            id: 'openai',
            displayName: 'OpenAI',
            models: [
              {
                provider: 'openai',
                id: 'gpt-5.4',
                name: 'GPT-5.4',
                api: 'responses',
                reasoning: true,
                thinkingLevels: ['off', 'low', 'medium', 'high'],
                supportsImages: true,
                contextWindow: 1_000_000,
                maxTokens: 128_000,
              },
            ],
          },
        ],
      };
    case 'agent.sessions.list':
      return {
        ok: true,
        sessions: [
          { id: 'session-preview', title: '控制中心迁移', status: 'ready', updatedAtMs: Date.now() },
          { id: 'session-memory', title: '记忆整理', status: 'idle', updatedAtMs: Date.now() - 360_000 },
        ],
      };
    case 'agent.rooms.list':
      return { ok: true, rooms: [] };
    case 'agent.roles.list':
      return { ok: true, roles: [] };
    case 'planning.dashboard':
      return { ok: true, date: new Date().toISOString().slice(0, 10), tasks: [], goals: [] };
    case 'memory.summary':
      return { ok: true, books: 12, atoms: 248, phrases: 640, groups: 9 };
    case 'memory.pages':
    case 'history.page':
      return { ok: true, items: [], nextCursor: '' };
    case 'configuration.settings':
      return { ok: true, configured: true, settings: {} };
    case 'configuration.schema':
      return { ok: true, sections: [] };
    default:
      return { ok: true, schemaVersion: 'rag-ime.control-preview.v1' };
  }
}
