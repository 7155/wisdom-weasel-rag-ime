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
    capabilities: { routeIds: Object.keys(routes) as ControlPathId[] },
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
          previewTool('ime_knowledge', '文档知识库', '检索用户明确启用的独立文档知识库', 'knowledge', 'R0', ['list_bases', 'search', 'find', 'open', 'status']),
        ],
      };
    case 'agent.subagents.list':
      return {
        ok: true,
        items: [previewSubagentBatch()],
      };
    case 'agent.subagent.get':
      return {
        ok: true,
        batch: previewSubagentBatch(),
      };
    case 'agent.artifact.get':
      return previewSubagentArtifact();
    case 'planning.dashboard':
      return { ok: true, date: new Date().toISOString().slice(0, 10), tasks: [], goals: [] };
    case 'memory.summary':
      return { ok: true, books: 12, atoms: 248, phrases: 640, groups: 9 };
    case 'memory.pages':
    case 'history.page':
      return { ok: true, items: [], nextCursor: '' };
    case 'knowledgeBases.list':
      return { ok: true, items: [previewKnowledgeBase()] };
    case 'knowledgeBases.get':
    case 'knowledgeBases.create':
    case 'knowledgeBases.update':
      return { ok: true, base: previewKnowledgeBase() };
    case 'knowledgeBases.documents.list':
      return {
        ok: true,
        items: [
          {
            id: 'file:preview-yuxi',
            baseId: 'kb:preview-project-docs',
            fileName: 'agent-runtime-notes.md',
            mimeType: 'text/markdown',
            byteSize: 48_320,
            status: 'ready',
            stage: 'ready',
            chunkCount: 36,
            parserProvider: 'builtin',
            revision: 1,
            updatedAtMs: Date.now() - 180_000,
          },
        ],
      };
    case 'knowledgeBases.jobs.list':
      return { ok: true, items: [] };
    case 'knowledgeBases.search':
      return {
        ok: true,
        items: [
          {
            chunkId: 'chunk:preview-agent-loop',
            documentId: 'file:preview-yuxi',
            documentName: 'agent-runtime-notes.md',
            heading: 'Agent Tool 边界',
            content: '文档知识库通过只读 Tool 按需检索，不会进入输入法候选热路径。',
            score: 0.92,
            citation: { page: 3, heading: 'Agent Tool 边界' },
          },
        ],
      };
    case 'knowledgeBases.graph.get':
      return {
        schemaVersion: 'rag-ime.knowledge-graph.v1',
        kbId: 'kb:preview-project-docs',
        revision: 1,
        sourceRevision: `sha256:${'a'.repeat(64)}`,
        status: 'ready',
        updatedAtMs: Date.now() - 60_000,
        nodes: [
          { id: 'doc:runtime', label: 'agent-runtime-notes.md', kind: 'document', documentId: 'file:preview-yuxi', documentName: 'agent-runtime-notes.md', weight: 1 },
          { id: 'topic:tools', label: 'Agent Tool 边界', kind: 'topic', weight: .9 },
          { id: 'entity:worker', label: 'Knowledge Worker', kind: 'entity', weight: .84 },
        ],
        edges: [
          { id: 'edge:doc-topic', source: 'doc:runtime', target: 'topic:tools', kind: 'contains', label: '包含', weight: .9 },
          { id: 'edge:topic-worker', source: 'topic:tools', target: 'entity:worker', kind: 'mentions', label: '提及', weight: .84 },
        ],
        stats: {
          nodeCount: 4,
          edgeCount: 3,
          documentCount: 1,
          chunkCount: 1,
          indexedDocumentCount: 1,
          pendingDocumentCount: 0,
        },
        truncated: false,
      };
    case 'knowledgeBases.graph.rebuild':
      return { ok: true, jobId: 'graph:preview-rebuild', status: 'queued' };
    case 'knowledgeBases.open':
      return { ok: true, items: [] };
    case 'knowledgeWorker.health':
      return { ok: true, available: true, status: 'ready', readyDocumentCount: 1 };
    case 'knowledgeParsers.list':
      return {
        ok: true,
        items: [
          { id: 'auto', name: '自动', available: true },
          { id: 'builtin', name: '内置解析', available: true },
          { id: 'mineru_local_http', name: 'MinerU', available: false, status: 'disabled' },
        ],
      };
    case 'configuration.settings':
      return { ok: true, configured: true, settings: {} };
    case 'configuration.schema':
      return { ok: true, sections: [] };
    default:
      return { ok: true, schemaVersion: 'rag-ime.control-preview.v1' };
  }
}

function previewKnowledgeBase(): Record<string, unknown> {
  return {
    id: 'kb:preview-project-docs',
    name: 'Agent Runtime 资料',
    description: '独立加载的项目文档与上游源码笔记。',
    documentCount: 1,
    chunkCount: 36,
    status: 'ready',
    agentEnabled: true,
    parserMode: 'auto',
    revision: 1,
    updatedAtMs: Date.now() - 120_000,
  };
}

function previewSubagentBatch(): Record<string, unknown> {
  const now = Date.now();
  const budget = {
    maxTurns: 10,
    maxToolCalls: 18,
    maxTotalTokens: 32_000,
    maxDurationMs: 300_000,
    maxOutputChars: 24_000,
  };
  const run = (
    id: string,
    templateId: 'researcher' | 'reviewer',
    task: string,
    state: 'running' | 'completed',
    ordinal: number,
  ) => ({
    schemaVersion: 'rag-ime.agent-subagent-run.v1',
    id,
    batchId: 'subagent-batch:preview',
    childSessionId: `subagent-runtime:${id}`,
    templateId,
    templateVersion: '1',
    ordinal,
    task,
    state,
    budget,
    usage: state === 'completed'
      ? { turnCount: 3, toolCount: 5, totalTokens: 4_820 }
      : { turnCount: 2, toolCount: 3, totalTokens: 2_140 },
    result: state === 'completed' ? { summary: '已核对来源与结论，结果已经交回主对话。' } : {},
    error: '',
    artifact: {
      schemaVersion: 'rag-ime.agent-artifact-ref.v1',
      artifactId: `artifact:${id}`,
      ownerKind: 'subagent_run',
      ownerId: id,
      kind: 'lifecycle',
      sha256: 'a'.repeat(64),
    },
    supervision: { phase: 'none', reason: '', requestedAtMs: null, graceMs: 0 },
    createdAtMs: now - (state === 'running' ? 68_000 : 180_000),
    startedAtMs: now - (state === 'running' ? 64_000 : 176_000),
    updatedAtMs: now - (state === 'running' ? 2_000 : 92_000),
    completedAtMs: state === 'completed' ? now - 92_000 : null,
  });
  return {
    schemaVersion: 'rag-ime.agent-subagent-batch.v1',
    id: 'subagent-batch:preview',
    parentSessionId: 'session-preview',
    state: 'running',
    runs: [
      run('subagent-run:research', 'researcher', '检索 Agent 状态投影和知识来源证据', 'running', 0),
      run('subagent-run:review', 'reviewer', '审阅前端交互与工具生命周期边界', 'completed', 1),
    ],
  };
}

function previewSubagentArtifact(): Record<string, unknown> {
  const now = Date.now();
  const records = [
    ['queued', '任务已进入并行队列'],
    ['started', '子智能体已经开始执行'],
    ['checkpoint', '已保存一次可恢复进度'],
  ].map(([eventType, summary], index) => ({
    schemaVersion: 'rag-ime.agent-artifact-record.v1',
    recordId: `preview-artifact:${index + 1}`,
    eventType,
    createdAtMs: now - (3 - index) * 20_000,
    payload: { summary },
  }));
  return {
    schemaVersion: 'rag-ime.agent-artifact-inspection.v1',
    artifact: {
      schemaVersion: 'rag-ime.agent-artifact-ref.v1',
      artifactId: 'artifact:subagent-run:research',
      ownerKind: 'subagent_run',
      ownerId: 'subagent-run:research',
      kind: 'lifecycle',
      mediaType: 'application/x-ndjson',
      appendOnly: true,
      byteSize: 512,
      sha256: 'a'.repeat(64),
      recordCount: records.length,
      snapshotRevision: 1,
      snapshotSha256: 'b'.repeat(64),
      createdAtMs: now - 80_000,
      updatedAtMs: now - 20_000,
    },
    records,
    totalRecords: records.length,
    returnedRecords: records.length,
    truncated: false,
    limits: { requestedRecords: 60, maxRecords: 500, maxOutputBytes: 262_144 },
  };
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
