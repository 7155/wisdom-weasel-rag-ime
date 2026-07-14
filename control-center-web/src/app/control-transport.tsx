import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { HttpControlTransport } from '@/platform/http-transport';
import { NativeBridgeUnavailableError, NativeControlTransport } from '@/platform/native-transport';
import { CONTROL_ROUTES, controlRoute, type ControlPathId } from '@/platform/routes';
import type { ControlRequest, ControlTransport } from '@/platform/transport';
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
  let nextSessionId = 1;
  const sessions: Record<string, unknown>[] = [
    previewSession('session-preview', '控制中心迁移', 'zhiyou-v1', Date.now()),
    previewSession('session-memory', '记忆整理', 'zhiyou-v1', Date.now() - 360_000),
  ];
  const routes = Object.fromEntries(
    (Object.keys(CONTROL_ROUTES) as ControlPathId[])
      .filter((pathId) => !controlRoute(pathId).subscription)
      .map((pathId) => [pathId, previewResponse(pathId)]),
  ) as Partial<Record<ControlPathId, MockRouteHandler>>;
  routes['agent.sessions.list'] = () => ({ ok: true, sessions: [...sessions] });
  routes['agent.sessions.create'] = (request: ControlRequest) => {
    const body = record(request.body);
    const session = previewSession(
      `session-persona-${nextSessionId++}`,
      stringValue(body.title) || '新对话',
      stringValue(body.roleId) || 'zhiyou-v1',
      Date.now(),
      stringValue(body.roleVersion) || '1',
    );
    sessions.unshift(session);
    return { ok: true, session };
  };
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
        selected: { provider: 'openai', id: 'gpt-5.4' },
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
    case 'agent.rooms.list':
      return { ok: true, rooms: [] };
    case 'agent.room.snapshot':
      return (request: ControlRequest) => previewRoomSnapshot(String(request.params?.roomId ?? 'room-preview'));
    case 'agent.roles.list':
      return { ok: true, roles: [] };
    case 'agent.tools.list':
      return {
        ok: true,
        items: [
          previewTool('control.overview', '控制中心概览', '查看输入法、模型、记忆和最近活动的整体状态', 'control', 'R0', ['status', 'capabilities', 'recent_activity']),
          previewTool('ime.input', '输入法', '查看输入设置、方案与候选解释，并在批准后调整配置或词表', 'input', 'R1', ['get_settings', 'preview_settings', 'apply_settings', 'rollback_settings', 'profile', 'candidate_explain', 'lexicon_review', 'lexicon_apply', 'lexicon_rollback']),
          previewTool('voice.input', '语音输入', '查看语音状态，并在批准后切换已配置的语音 Provider', 'voice', 'R1', ['status', 'privacy_policy', 'provider_status', 'provider_preview', 'provider_apply', 'provider_rollback']),
          previewTool('planning.tasks', '规划与任务', '查看每日计划，并在确认后更新任务状态', 'planning', 'R1', ['dashboard', 'task_action', 'undo_task_event']),
          previewTool('ime.memory', '记忆与工具书', '渐进查询 Memory Book，并通过可审阅草案维护长期记忆', 'memory', 'R1', ['catalog', 'read', 'recent', 'trace', 'maintenance_status', 'maintenance_preview', 'maintenance_review', 'maintenance_apply', 'maintenance_rollback', 'list', 'search']),
          previewTool('ime.knowledge', '知识检索', '执行有来源的本地 RAG 召回并检查深度检索路由', 'knowledge', 'R0', ['recall', 'deep_recall', 'route_status']),
        ],
      };
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

function previewSession(
  id: string,
  title: string,
  roleId: string,
  updatedAtMs: number,
  roleVersion = '1',
): Record<string, unknown> {
  return {
    id,
    title,
    mode: 'assistant',
    status: 'ready',
    roleId,
    roleVersion,
    updatedAtMs,
    workspaceRoots: [],
    modelProfile: 'session-selected',
    messageCount: 0,
    lastMessagePreview: '',
  };
}

function previewTool(
  id: string,
  displayName: string,
  description: string,
  domain: string,
  riskLevel: string,
  operations: string[],
): Record<string, unknown> {
  return {
    schemaVersion: 'rag-ime.control-tool-manifest.v1',
    id,
    displayName,
    description,
    domain,
    category: domain,
    riskLevel,
    sessionModes: ['assistant', 'coordinator'],
    operations,
    operationRisks: Object.fromEntries(operations.map((operation) => [operation, riskLevel])),
    resultPresentation: 'tool_result',
    availability: 'online',
    version: 'preview',
  };
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function previewRoomSnapshot(roomId: string) {
  const now = Date.now() - 60_000;
  const participants = [
    previewParticipant(roomId, 'participant-zhiyou', 'session-preview', 'zhiyou-v1', '智鼬·此刻', 0),
    previewParticipant(roomId, 'participant-hermes', 'session-runtime', 'hermes-v1', '智鼬·初识', 1),
  ];
  const event = (
    sequence: number,
    eventType: string,
    participantId: string | null,
    payload: Record<string, unknown>,
  ) => ({
    schemaVersion: 'rag-ime.agent-room-event.v1',
    eventId: `${roomId}:${sequence}`,
    roomId,
    sequence,
    turnId: `${roomId}:turn-1`,
    eventType,
    participantId,
    sourceSessionId: '',
    createdAtMs: now + sequence,
    payload,
    resumeToken: `${roomId}:${sequence}`,
  });
  const events = [
    event(1, 'user_message', null, { messageId: 'room-user-1', text: '并行检查 Agent UI 与 Control API 的集成边界。' }),
    event(2, 'route_decision', null, { summary: '主持人将任务分给 2 个 Agent' }),
    event(3, 'participant_activity', 'participant-zhiyou', { requestId: 'activity-a', summary: '核对 Turn 聚合与流式投影', status: 'completed' }),
    event(4, 'participant_activity', 'participant-hermes', { requestId: 'activity-b', summary: '核对 route policy 与权限回执', status: 'completed' }),
    event(5, 'participant_delta', 'participant-zhiyou', { messageId: 'room-assistant-1', delta: 'Agent 时间线已经复用统一 reducer 与 batcher，' }),
    event(6, 'participant_delta', 'participant-zhiyou', { messageId: 'room-assistant-1', delta: '主时间线不会平铺每个工具结果。' }),
    event(7, 'participant_delta', 'participant-hermes', { messageId: 'room-assistant-2', delta: '权限切换只在服务端回执后更新。' }),
    event(8, 'turn_completed', null, { summary: '协作检查完成' }),
  ];
  return {
    schemaVersion: 'rag-ime.agent-room-snapshot.v1',
    ok: true,
    room: {
      schemaVersion: 'rag-ime.agent-room.v1',
      id: roomId,
      title: '迁移作战室',
      status: 'active',
      routingPolicy: 'moderator',
      moderatorParticipantId: 'participant-zhiyou',
      createdAtMs: now,
      updatedAtMs: now + events.length,
      lastEventSequence: events.length,
      participants,
    },
    events,
    firstSequence: 1,
    lastSequence: events.length,
    resumeToken: `${roomId}:${events.length}`,
    truncated: false,
  };
}

function previewParticipant(
  roomId: string,
  id: string,
  sessionId: string,
  roleId: string,
  displayName: string,
  ordinal: number,
) {
  return {
    schemaVersion: 'rag-ime.agent-participant.v1',
    id,
    roomId,
    sessionId,
    roleId,
    roleVersion: '1',
    displayName,
    status: 'active',
    ordinal,
    createdAtMs: 1,
    lastSpokeAtMs: null,
  };
}
