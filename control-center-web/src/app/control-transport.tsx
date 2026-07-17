import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { HttpControlTransport } from '@/platform/http-transport';
import { NativeBridgeUnavailableError, NativeControlTransport } from '@/platform/native-transport';
import { CONTROL_ROUTES, controlRoute, type ControlPathId } from '@/platform/routes';
import type { ControlRequest, ControlTransport } from '@/platform/transport';
import { MockControlTransport, type MockRouteHandler } from '@/test/mock-transport';
import { previewPersonas } from '@/features/agent/preview-data';

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
  let nextWakeScheduleId = 1;
  let previewEvidenceDisposition = 'not_for_memory';
  let previewMemoryRunStatus = 'draft';
  const previewMemorySelections = new Map<number, boolean>([[1, true], [2, false], [3, true]]);
  const sessions: Record<string, unknown>[] = [
    previewSession('session-preview', '控制中心迁移', 'zhiyou-v1', Date.now()),
    previewSession('session-memory', '记忆整理', 'zhiyou-v1', Date.now() - 360_000),
  ];
  const wakeSchedules: Record<string, unknown>[] = [];
  const routes = Object.fromEntries(
    (Object.keys(CONTROL_ROUTES) as ControlPathId[])
      .filter((pathId) => !controlRoute(pathId).subscription)
      .map((pathId) => [pathId, previewResponse(pathId)]),
  ) as Partial<Record<ControlPathId, MockRouteHandler>>;
  routes['memory.summary'] = () => previewMemorySummary();
  routes['memory.graph.get'] = (request: ControlRequest) =>
    previewMemoryGraph(stringValue(record(request.query).plane) === 'tags' ? 'tags' : 'groups');
  routes['memory.entity.get'] = (request: ControlRequest) => previewMemoryEntity(
    stringValue(record(request.params).kind),
    stringValue(record(request.params).entityId),
  );
  routes['agent.memoryMaintenance.run'] = (request: ControlRequest) =>
    stringValue(record(request.query).runId)
      ? previewMemoryCurationRun(previewMemorySelections, previewMemoryRunStatus)
      : previewMemoryCurationStatus(previewMemoryRunStatus);
  routes['knowledge.database.draft.edit'] = (request: ControlRequest) => {
    const body = record(request.body);
    const diffId = Number(body.diffId);
    if (previewMemoryRunStatus !== 'draft' || !previewMemorySelections.has(diffId)) {
      throw new Error('The preview memory draft is no longer editable.');
    }
    previewMemorySelections.set(diffId, body.selected === true);
    return {
      ok: true,
      runId: 'memory_book_preview',
      diffId,
      selected: body.selected === true,
    };
  };
  routes['knowledge.database.apply.preview'] = () => previewMemoryApplyPreview();
  routes['knowledge.database.apply'] = () => {
    previewMemoryRunStatus = 'applied';
    return previewMemoryWorkReceipt('knowledge.database.apply', true);
  };
  routes['knowledge.database.rollback'] = () => {
    previewMemoryRunStatus = 'rolled_back';
    return previewMemoryWorkReceipt('knowledge.database.rollback', false);
  };
  routes['agent.sessions.list'] = (request: ControlRequest) => ({
    ok: true,
    sessions: sessions.filter((session) => (
      record(request.query).includeArchived === true || stringValue(session.status) !== 'archived'
    )),
  });
  routes['agent.roles.list'] = () => ({ ok: true, roles: previewPersonas });
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
  routes['agent.session.archive'] = (request: ControlRequest) => {
    const sessionId = stringValue(record(request.params).sessionId);
    const index = sessions.findIndex((session) => stringValue(session.id) === sessionId);
    const archived = record(request.body).archived === true;
    if (index < 0) throw new Error('Preview session not found.');
    sessions[index] = {
      ...sessions[index],
      status: archived ? 'archived' : 'idle',
      updatedAtMs: Date.now(),
    };
    return { ok: true, session: sessions[index] };
  };
  routes['agent.session.delete'] = (request: ControlRequest) => {
    const sessionId = stringValue(record(request.params).sessionId);
    const index = sessions.findIndex((session) => stringValue(session.id) === sessionId);
    if (index >= 0) sessions.splice(index, 1);
    return { ok: true, sessionId };
  };
  routes['agent.session.forks.list'] = (request: ControlRequest) => ({
    schemaVersion: 'rag-ime.agent-session-fork-candidates.v1',
    ok: true,
    sessionId: stringValue(record(request.params).sessionId) || 'session-preview',
    items: [
      { entryId: 'session-preview:user-architecture', text: '把迁移进度按真实代码链整理一下，别把工具日志当回答。', role: 'user', createdAtMs: 0 },
      { entryId: 'session-preview:assistant-architecture', text: '三条 Lane 已经收束到同一个可执行计划。', role: 'assistant', createdAtMs: 0 },
      { entryId: 'session-preview:user-media', text: '把完成状态和附件也保留成结构化块。', role: 'user', createdAtMs: 0 },
      { entryId: 'session-preview:assistant-media', text: '已完成。活动明细仍可追溯，附件也已经登记。', role: 'assistant', createdAtMs: 0 },
    ],
  });
  routes['agent.session.forks.create'] = (request: ControlRequest) => {
    const body = record(request.body);
    const sourceSessionId = stringValue(record(request.params).sessionId) || 'session-preview';
    const entryId = stringValue(body.entryId) || 'session-preview:user-media';
    const selectedText = ({
      'session-preview:user-architecture': '把迁移进度按真实代码链整理一下，别把工具日志当回答。',
      'session-preview:assistant-architecture': '',
      'session-preview:user-media': '把完成状态和附件也保留成结构化块。',
      'session-preview:assistant-media': '',
    } as Record<string, string>)[entryId] ?? '从这里创建分支。';
    const now = Date.now();
    const session = {
      ...previewSession(
        `session-fork-${nextSessionId++}`,
        stringValue(body.title) || '对话分支',
        'zhiyou-v1',
        now,
      ),
      schemaVersion: 'rag-ime.agent-session.v1',
      status: 'idle',
      modelProfile: 'session-selected',
      toolProfileVersion: 'control-center-v1',
      createdAtMs: now,
      messageCount: 2,
    };
    sessions.unshift(session);
    return {
      schemaVersion: 'rag-ime.agent-session-fork-create.v1',
      ok: true,
      sourceSessionId,
      entryId,
      selectedText,
      session,
    };
  };
  routes['agent.wakeSchedules.list'] = () => ({ ok: true, schedulerActive: true, items: [...wakeSchedules] });
  routes['agent.wakeSchedules.create'] = (request: ControlRequest) => {
    const body = record(request.body);
    const now = Date.now();
    const schedule = {
      id: `wake:preview-${nextWakeScheduleId++}`,
      title: stringValue(body.title) || '预览预约',
      instruction: stringValue(body.instruction),
      targetType: stringValue(body.targetType) || 'session',
      targetSessionId: stringValue(body.targetSessionId),
      targetRoleId: stringValue(body.targetRoleId),
      targetRoleVersion: stringValue(body.targetRoleVersion),
      planningTaskId: stringValue(body.planningTaskId),
      timezone: stringValue(body.timezone) || 'Asia/Shanghai',
      recurrenceKind: stringValue(body.recurrenceKind) || 'once',
      recurrenceInterval: Number(body.recurrenceInterval) || 1,
      maxRuns: Number(body.maxRuns) || 1,
      runCount: 0,
      status: 'scheduled',
      nextWakeAtMs: Number(body.wakeAtMs) || now + 30 * 60_000,
      lastWakeAtMs: 0,
      lastError: '',
      createdAtMs: now,
      updatedAtMs: now,
      latestRun: {},
    };
    wakeSchedules.unshift(schedule);
    return { ok: true, schedule };
  };
  routes['agent.wakeSchedule.action'] = (request: ControlRequest) => {
    const scheduleId = stringValue(record(request.params).scheduleId);
    const schedule = wakeSchedules.find((item) => item.id === scheduleId);
    if (!schedule) throw new Error('预约不存在');
    const action = stringValue(record(request.body).action);
    schedule.status = ({ pause: 'paused', resume: 'scheduled', cancel: 'cancelled', retry: 'scheduled' } as Record<string, string>)[action] ?? schedule.status;
    schedule.updatedAtMs = Date.now();
    if (action === 'retry') schedule.nextWakeAtMs = Date.now() + 1_000;
    return { ok: true, schedule: { ...schedule } };
  };
  routes['agent.wakeSchedule.runs'] = (request: ControlRequest) => {
    const scheduleId = stringValue(record(request.params).scheduleId);
    return {
      ok: true,
      schedule: wakeSchedules.find((item) => item.id === scheduleId) ?? {},
      items: [],
    };
  };
  routes['memory.pages'] = (request: ControlRequest) =>
    previewMemoryPage(request, previewEvidenceDisposition);
  routes['memory.source.disposition'] = (request: ControlRequest) => {
    const disposition = stringValue(record(request.body).disposition);
    if (disposition === 'pending' || disposition === 'not_for_memory') {
      previewEvidenceDisposition = disposition;
    }
    return { ok: true, changed: true };
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
    case 'observability.snapshot':
      return (request: ControlRequest) =>
        previewObservationSnapshot(record(request.query));
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
        capabilities: { conversationFork: true, conversationRewrite: true },
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
    case 'agent.session.contextItems.list':
      return { ok: true, items: [] };
    case 'agent.session.contextTraces.list':
      return {
        ok: true,
        items: [{
          traceId: 'context-trace:preview',
          sessionId: 'session-preview',
          turnId: 'turn-preview',
          sourceKind: 'user',
          status: 'accepted',
          finalFingerprint: 'sha256:0123456789abcdef',
          nodeCount: 5,
          createdAtMs: Date.now() - 18_000,
          updatedAtMs: Date.now() - 17_000,
        }],
      };
    case 'agent.session.contextTrace.get':
      return (request: ControlRequest) => previewContextTrace(
        stringValue(record(request.params).sessionId) || 'session-preview',
        stringValue(record(request.params).traceId) || 'context-trace:preview',
      );
    case 'agent.session.debugContext.get':
      return (request: ControlRequest) => previewDebugContext(
        stringValue(record(request.params).sessionId) || 'session-preview',
        stringValue(record(request.query).turnId) || 'turn-preview',
      );
    case 'agent.rooms.list':
      return { ok: true, rooms: [previewRoomSnapshot('room-preview').room] };
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
          previewTool('ime.memory', '记忆与工具书', '查询 Memory Book，并生成 Atom-first 可审阅草案', 'memory', 'R1', ['catalog', 'read', 'recent', 'trace', 'maintenance_status', 'curation_prepare', 'maintenance_preview', 'maintenance_review', 'maintenance_apply', 'maintenance_rollback', 'list', 'search']),
          previewTool('ime_knowledge', '文档知识库', '检索用户明确启用的独立文档知识库', 'knowledge', 'R0', ['list_bases', 'search', 'find', 'open', 'status']),
          previewTool('ime_browser', '浏览器共驾', '读取已配对浏览器的页面，并在批准后执行可追踪操作', 'browser', 'R1', ['status', 'tabs', 'snapshot', 'screenshot', 'trace', 'navigate', 'click', 'type', 'scroll', 'wait', 'stop']),
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
      return {
        ok: true,
        runtimeRevision: 43,
        eventCount: 1_284,
        memoryItemCount: 326,
        evidenceSourceCount: 1_108,
        memoryBookCount: 12,
        memoryAtomCount: 248,
        forgottenSourceCount: 37,
        needsReviewSourceCount: 4,
        owners: [
          { ownerKind: 'user', ownerId: 'default', itemCount: 292 },
          { ownerKind: 'agent', ownerId: 'zhiyou-v1', itemCount: 34 },
        ],
      };
    case 'memory.pages':
    case 'history.page':
      return { ok: true, items: [], nextCursor: '' };
    case 'memory.source.disposition':
      return { ok: true, changed: true };
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
    case 'browser.status':
      return {
        ok: true,
        mode: 'codrive',
        clients: [{
          deviceId: 'chrome-preview',
          displayName: '我的 Chrome',
          clientKind: 'user',
          connected: true,
          activeTabId: 23,
        }],
        latestSnapshot: previewBrowserSnapshot(),
        managedBrowser: {
          running: false,
          profilePath: '~/Library/Application Support/RagIme/BrowserCopilot/managed-profile',
        },
      };
    case 'browser.pairing':
      return {
        ok: true,
        pairingToken: 'preview-pairing-token',
        tokenFingerprint: 'preview-4d7a',
        extensionPath: '~/Library/Application Support/RagIme/BrowserCopilot/extension',
        bridgeUrl: 'http://127.0.0.1:8766',
      };
    case 'browser.tabs':
      return {
        ok: true,
        items: [{
          deviceId: 'chrome-preview',
          tabId: 23,
          title: 'Agent Runtime 架构',
          url: 'https://docs.example.com/agent-runtime',
          active: true,
        }],
      };
    case 'browser.snapshot.latest':
      return previewBrowserSnapshot();
    case 'browser.permissions':
      return {
        ok: true,
        items: [{
          promptId: 'bperm-preview',
          deviceId: 'chrome-preview',
          origin: 'https://research.example.com',
          action: 'domain_transition',
          reason: '首次进入调研站点',
          status: 'pending',
          decision: '',
          createdAtMs: Date.now() - 36_000,
        }],
      };
    case 'browser.traces':
      return {
        ok: true,
        items: [{
          commandId: 'bcmd-preview',
          action: 'snapshot',
          status: 'completed',
          durationMs: 184,
          result: { summary: '已读取 3 个 Frame 和 18 个可交互元素' },
        }],
      };
    case 'browser.mode.update':
    case 'browser.pairing.rotate':
    case 'browser.command':
    case 'browser.stop':
    case 'browser.managed.start':
    case 'browser.managed.stop':
    case 'browser.permission.decide':
      return { ok: true };
    case 'configuration.settings':
      return { ok: true, configured: true, settings: {} };
    case 'configuration.schema':
      return { ok: true, sections: [] };
    default:
      return { ok: true, schemaVersion: 'rag-ime.control-preview.v1' };
  }
}

function previewMemoryPage(
  request: ControlRequest,
  evidenceDisposition: string,
): Record<string, unknown> {
  const kind = stringValue(record(request.params).kind);
  if (kind === 'evidence') {
    return {
      ok: true,
      items: [
        {
          id: 'input-memory:preview-noise',
          title: '嗯嗯那个这个',
          detail: evidenceDisposition === 'not_for_memory'
            ? 'input_noise_filler'
            : 'user_restored',
          status: evidenceDisposition,
          disposition: evidenceDisposition,
          source: 'squirrel_rime_commit_burst',
          type: 'user_final',
          ownerKind: 'user',
          ownerId: 'default',
          updatedAtMs: Date.now() - 86_400_000,
        },
        {
          id: 'agent-memory:preview-compaction',
          title: '桌面上下文默认读取 Accessibility Tree，截图仅作兜底。',
          detail: 'durable_role_summary',
          status: 'remember',
          disposition: 'remember',
          source: 'pi_agent_compaction',
          type: 'session_compaction',
          ownerKind: 'agent',
          ownerId: 'zhiyou-v1',
          updatedAtMs: Date.now() - 3_600_000,
        },
      ],
      nextCursor: '',
      limit: 50,
    };
  }
  if (kind === 'books') {
    return {
      ok: true,
      items: [
        {
          id: 'book:preview-memory-governance',
          title: '记忆治理与桌面上下文',
          summary: '按用户、角色和项目隔离证据；每日整理先生成可审阅草案。',
          status: 'active',
          source: 'memory_book',
          type: 'topic',
          ownerKind: 'user',
          ownerId: 'default',
          tags: ['记忆治理', '桌面上下文'],
          updatedAtMs: Date.now() - 7_200_000,
        },
      ],
      nextCursor: '',
      limit: 50,
    };
  }
  return previewMemoryCatalogPage(kind);
}

function previewBrowserSnapshot(): Record<string, unknown> {
  return {
    ok: true,
    snapshotId: 'snap-preview-runtime',
    deviceId: 'chrome-preview',
    tabId: 23,
    url: 'https://docs.example.com/agent-runtime',
    title: 'Agent Runtime 架构',
    summary: '3 个 Frame · 18 个可交互元素',
    markdown: [
      '# Agent Runtime 架构',
      'URL: https://docs.example.com/agent-runtime',
      '当前页面说明浏览器快照如何进入 Agent Tool。',
      '## 页面操作',
      '- [0:e1] button "运行验证"',
      '- [0:e2] link "查看执行轨迹"',
      '- [0:e3] textbox "输入检索问题"',
      '## 安全边界',
      '密码字段不会进入页面快照，跨站导航需要单独批准。',
    ].join('\n'),
    interactiveCount: 18,
    hasScreenshot: false,
    createdAtMs: Date.now() - 2_000,
  };
}

function previewObservationSnapshot(filters: Record<string, unknown> = {}) {
  const now = Date.now();
  const source = [
    {
      category: 'runtime',
      phase: 'turn_completed',
      name: 'turn_completed',
      status: 'completed',
      summary: 'Agent 回合已完成',
      durationMs: 3_842,
      metrics: { messageCount: 4 },
      sequence: 8,
    },
    {
      category: 'memory',
      phase: 'draft_ready',
      name: 'memory_curation',
      status: 'waiting',
      summary: '记忆整理草案已生成，等待审阅',
      durationMs: 1_620,
      metrics: { eventCount: 48, changeCount: 7 },
      sequence: 7,
    },
    {
      category: 'tool',
      phase: 'tool_finished',
      name: 'tool_finished',
      status: 'completed',
      summary: 'ime.memory 已完成',
      durationMs: 486,
      metrics: { argumentFieldCount: 3, resultFieldCount: 5 },
      sequence: 6,
    },
    {
      category: 'retrieval',
      phase: 'retrieval_complete',
      name: 'active_rag_retrieval',
      status: 'completed',
      summary: '闪电联想检索已完成',
      durationMs: 72,
      metrics: { evidenceCount: 9 },
      sequence: 5,
    },
    {
      category: 'context',
      phase: 'started',
      name: 'active_rag_context',
      status: 'completed',
      summary: '闪电联想已捕获上下文元数据',
      durationMs: 0,
      metrics: { selectedChars: 18, contextChars: 126 },
      sequence: 4,
    },
    {
      category: 'intercom',
      phase: 'delivered',
      name: 'participant_activity',
      status: 'completed',
      summary: 'Agent 私信已送达',
      durationMs: 118,
      metrics: {},
      sequence: 3,
    },
    {
      category: 'approval',
      phase: 'approval_required',
      name: 'approval_required',
      status: 'waiting',
      summary: '运行步骤等待用户确认',
      durationMs: null,
      metrics: {},
      sequence: 2,
    },
    {
      category: 'agent',
      phase: 'status_changed',
      name: 'status_changed',
      status: 'running',
      summary: 'Agent 正在分析',
      durationMs: null,
      metrics: {},
      sequence: 1,
    },
  ] as const;
  const allItems = source.map((item) => ({
    schemaVersion: 'rag-ime.observation-event.v1',
    eventType: 'observation',
    eventId: `observation:preview:${item.sequence}`,
    sequence: item.sequence,
    resumeToken: `observation:${item.sequence}`,
    traceId: item.category === 'context' || item.category === 'retrieval'
      ? 'trace:active-rag:preview'
      : item.category === 'intercom'
        ? 'trace:room-turn:preview'
        : 'trace:turn:preview',
    spanId: `span:preview:${item.sequence}`,
    parentSpanId: item.sequence === 1 ? '' : `span:preview:${Math.max(1, item.sequence - 1)}`,
    sessionId: item.category === 'context' || item.category === 'retrieval'
      ? 'active-rag:preview'
      : 'session-preview',
    roomId: item.category === 'intercom' ? 'room-preview' : '',
    turnId: item.category === 'context' || item.category === 'retrieval' ? '' : 'turn-preview',
    runId: item.category === 'memory' ? 'memory_book_preview' : '',
    category: item.category,
    phase: item.phase,
    name: item.name,
    status: item.status,
    summary: item.summary,
    createdAtMs: now - (8 - item.sequence) * 19_000,
    startedAtMs: now - (8 - item.sequence) * 19_000,
    endedAtMs: ['completed', 'failed', 'cancelled'].includes(item.status)
      ? now - (8 - item.sequence) * 19_000
      : null,
    durationMs: item.durationMs,
    privacyClass: 'redacted',
    metrics: item.metrics,
    attributes: { rawTextStored: false },
    refs: [],
  }));
  const items = allItems.filter((item) => (
    (!stringValue(filters.category) || item.category === stringValue(filters.category))
    && (!stringValue(filters.status) || item.status === stringValue(filters.status))
    && (!stringValue(filters.sessionId) || item.sessionId === stringValue(filters.sessionId))
    && (!stringValue(filters.roomId) || item.roomId === stringValue(filters.roomId))
    && (!stringValue(filters.traceId) || item.traceId === stringValue(filters.traceId))
  ));
  const byCategory: Record<string, number> = {};
  const byStatus: Record<string, number> = {};
  for (const item of items) {
    byCategory[item.category] = (byCategory[item.category] ?? 0) + 1;
    byStatus[item.status] = (byStatus[item.status] ?? 0) + 1;
  }
  return {
    schemaVersion: 'rag-ime.observation-snapshot.v1',
    generatedAtMs: now,
    firstSequence: 1,
    lastSequence: 8,
    resumeToken: 'observation:8',
    truncated: false,
    filters: Object.fromEntries(
      Object.entries(filters).filter(([, value]) => stringValue(value)),
    ),
    counts: {
      total: items.length,
      byCategory,
      byStatus,
    },
    items,
  };
}

function previewMemorySummary(): Record<string, unknown> {
  return {
    ok: true,
    runtimeRevision: 7,
    appCount: 4,
    completeInputCount: 3_602,
    blockedFragmentCount: 4_887,
    memoryBookCount: 15,
    memoryAtomCount: 123,
    memoryTagCount: 93,
    pendingCompileEvents: 0,
    evidenceSourceCount: 2,
    forgottenSourceCount: 1,
    needsReviewSourceCount: 0,
    owners: [
      { ownerKind: 'user', ownerId: 'default', itemCount: 124 },
      { ownerKind: 'agent', ownerId: 'zhiyou-v1', itemCount: 16 },
    ],
  };
}

function previewMemoryCatalogPage(kind: string): Record<string, unknown> {
  const common = { ok: true, nextCursor: '', limit: 50 };
  if (kind === 'apps') {
    return {
      ...common,
      rawTextVisible: false,
      items: [
        previewAppMemory('com.openai.codex', 'Codex', 3_501, 89, 8, Date.now() - 42_000),
        previewAppMemory('com.mitchellh.ghostty', 'Ghostty', 67, 10, 1, Date.now() - 320_000),
        previewAppMemory('com.microsoft.VSCode', 'VS Code', 26, 5, 1, Date.now() - 840_000),
        previewAppMemory('com.microsoft.edgemac', 'Edge', 8, 7, 0, Date.now() - 1_500_000),
      ],
    };
  }
  if (kind === 'tags') {
    return {
      ...common,
      items: [
        { id: 'agent-runtime', tag: 'Agent Runtime', description: '会话、工具与执行边界', item_count: 18, edge_count: 2, color_token: 'teal', status: 'active', source: 'agent' },
        { id: 'memory-quality', tag: '记忆质量', description: '去噪、合并与来源约束', item_count: 14, edge_count: 2, color_token: 'green', status: 'active', source: 'agent' },
        { id: 'input-boundary', tag: '输入封口', description: 'Backspace 编辑，Enter 后持久化', item_count: 9, edge_count: 2, color_token: 'orange', status: 'active', source: 'agent' },
      ],
    };
  }
  if (kind === 'groups') {
    return {
      ...common,
      items: [
        { id: 'group:input-method', title: '输入法', note: '输入质量、候选与上下文注入', tags: ['输入封口', '记忆质量'], event_count: 34, color_token: 'teal', status: 'active', source: 'agent' },
        { id: 'group:agent', title: 'Agent 工程', note: '会话、工具和长期记忆', tags: ['Agent Runtime', '记忆质量'], event_count: 27, color_token: 'blue', status: 'active', source: 'agent' },
      ],
    };
  }
  if (kind === 'atoms') {
    return {
      ...common,
      items: [
        { id: 'atom:input-boundary', title: '输入段封口规则', text: 'Backspace 修改当前缓冲区，Enter 或切换 App 后才形成完整输入段。', status: 'active', source: 'agent', tags: ['输入封口', '记忆质量'], updatedAtMs: Date.now() - 120_000 },
        { id: 'atom:lightning', title: '闪电联想上下文', text: '闪电联想只读取进程内实时缓冲，不把未封口碎片写进普通 Agent 上下文。', status: 'active', source: 'agent', tags: ['输入法', 'Agent Runtime'], updatedAtMs: Date.now() - 240_000 },
      ],
    };
  }
  if (kind === 'phrases') {
    return { ...common, items: [{ id: 'phrase:memory-curator', text: '记忆整理 Skill', status: 'approved', source: 'agent', updatedAtMs: Date.now() - 360_000 }] };
  }
  if (kind === 'negative') {
    return { ...common, items: [{ id: 'negative:rime-fragment', reason: '未封口的 Rime 单词碎片不得注入上下文', active: true, status: 'active', source: 'input_quality', updatedAtMs: Date.now() - 480_000 }] };
  }
  return {
    ...common,
    items: [
      { id: 'book:input-memory', type: 'topic', title: '输入法记忆与上下文', summary: '完整输入段、App 来源和闪电联想边界', status: 'active', source: 'agent', tags: ['输入封口', '记忆质量'], updatedAtMs: Date.now() - 90_000 },
      { id: 'book:agent-runtime', type: 'topic', title: 'Agent Runtime', summary: 'Pi Skill、会话与受控写入', status: 'active', source: 'agent', tags: ['Agent Runtime'], updatedAtMs: Date.now() - 210_000 },
    ],
  };
}

function previewAppMemory(
  id: string,
  title: string,
  eventCount: number,
  atomCount: number,
  bookCount: number,
  latestAtMs: number,
): Record<string, unknown> {
  return {
    id,
    title,
    detail: `${eventCount} 段完整输入 · ${atomCount} 个记忆原子 · ${bookCount} 本主题书`,
    source: 'input_app',
    status: 'active',
    type: 'app',
    bundleId: id,
    eventCount,
    finalizedSegmentCount: Math.min(eventCount, Math.max(0, Math.round(eventCount * 0.72))),
    contextGroupCount: Math.max(1, Math.round(eventCount / 18)),
    atomCount,
    bookCount,
    latestAtMs,
  };
}

function previewMemoryGraph(plane: 'groups' | 'tags'): Record<string, unknown> {
  const runtime = previewMemoryGraphNode('tag:agent-runtime', 'tag', 'Agent Runtime', '会话、工具与执行边界', 18, 'teal');
  const quality = previewMemoryGraphNode('tag:memory-quality', 'tag', '记忆质量', '去噪、合并与来源约束', 14, 'green');
  const boundary = previewMemoryGraphNode('tag:input-boundary', 'tag', '输入封口', 'Backspace 编辑，Enter 后持久化', 9, 'orange');
  const tags = [runtime, quality, boundary];
  if (plane === 'tags') {
    return previewMemoryGraphEnvelope(plane, tags, [
      previewMemoryGraphEdge('tag-edge:runtime-quality', 'tagRelation', 'tag:agent-runtime', 'tag:memory-quality', 'related_to', 0.92, 8),
      previewMemoryGraphEdge('tag-edge:quality-boundary', 'tagRelation', 'tag:memory-quality', 'tag:input-boundary', 'depends_on', 0.88, 6),
      previewMemoryGraphEdge('tag-edge:boundary-runtime', 'tagRelation', 'tag:input-boundary', 'tag:agent-runtime', 'feeds', 0.74, 4),
    ]);
  }
  const inputGroup = previewMemoryGraphNode('group:input-method', 'group', '输入法', '输入质量、候选与上下文注入', 34, 'teal');
  const agentGroup = previewMemoryGraphNode('group:agent', 'group', 'Agent 工程', '会话、工具和长期记忆', 27, 'blue');
  const book = previewMemoryGraphNode('book:input-memory', 'book', '输入法记忆与上下文', '完整输入段、App 来源和闪电联想边界', 12, 'green');
  return previewMemoryGraphEnvelope(plane, [inputGroup, agentGroup, book, ...tags], [
    previewMemoryGraphEdge('member:input-boundary', 'groupMember', 'group:input-method', 'tag:input-boundary', 'contains', 1, 1),
    previewMemoryGraphEdge('member:input-quality', 'groupMember', 'group:input-method', 'tag:memory-quality', 'contains', 1, 1),
    previewMemoryGraphEdge('member:input-book', 'groupMember', 'group:input-method', 'book:input-memory', 'contains', 0.9, 1),
    previewMemoryGraphEdge('member:agent-runtime', 'groupMember', 'group:agent', 'tag:agent-runtime', 'contains', 1, 1),
    previewMemoryGraphEdge('member:agent-quality', 'groupMember', 'group:agent', 'tag:memory-quality', 'contains', 0.85, 1),
  ]);
}

function previewMemoryGraphEnvelope(
  plane: 'groups' | 'tags',
  nodes: Record<string, unknown>[],
  edges: Record<string, unknown>[],
): Record<string, unknown> {
  return {
    schemaVersion: 'rag-ime.memory-graph.v1',
    ok: true,
    settingsRevision: 'settings:preview',
    runtimeRevision: 7,
    graphRevision: `sha256:${'a'.repeat(64)}`,
    plane,
    project: 'wisdom-weasel-rag-ime',
    filters: { status: 'active', query: '', focusId: '', minWeight: 0 },
    nodes,
    edges,
    truncated: { nodes: false, edges: false },
    limits: { nodeLimit: 48, edgeLimit: 160, depth: 1 },
  };
}

function previewMemoryGraphNode(
  id: string,
  kind: 'tag' | 'group' | 'book',
  label: string,
  description: string,
  memberCount: number,
  color: string,
): Record<string, unknown> {
  return {
    id,
    entityId: id.slice(id.indexOf(':') + 1),
    kind,
    label,
    description,
    color,
    status: 'active',
    source: 'preview',
    project: 'wisdom-weasel-rag-ime',
    qualityScore: 1,
    memberCount,
    edgeCount: 2,
    updatedAtMs: Date.now() - 60_000,
  };
}

function previewMemoryGraphEdge(
  id: string,
  kind: 'tagRelation' | 'groupMember',
  sourceId: string,
  targetId: string,
  relation: string,
  weight: number,
  evidenceCount: number,
): Record<string, unknown> {
  return {
    id,
    kind,
    sourceId,
    targetId,
    sourceKind: sourceId.split(':', 1)[0],
    targetKind: targetId.split(':', 1)[0],
    relation,
    weight,
    directionBias: 0,
    evidenceCount,
    source: 'preview',
    updatedAtMs: Date.now() - 60_000,
  };
}

function previewMemoryEntity(kindValue: string, entityId: string): Record<string, unknown> {
  const kind = kindValue === 'group' || kindValue === 'book' ? kindValue : 'tag';
  const catalog = {
    'agent-runtime': previewMemoryGraphNode('tag:agent-runtime', 'tag', 'Agent Runtime', '会话、工具与执行边界', 18, 'teal'),
    'memory-quality': previewMemoryGraphNode('tag:memory-quality', 'tag', '记忆质量', '去噪、合并与来源约束', 14, 'green'),
    'input-boundary': previewMemoryGraphNode('tag:input-boundary', 'tag', '输入封口', 'Backspace 编辑，Enter 后持久化', 9, 'orange'),
    'input-method': previewMemoryGraphNode('group:input-method', 'group', '输入法', '输入质量、候选与上下文注入', 34, 'teal'),
    agent: previewMemoryGraphNode('group:agent', 'group', 'Agent 工程', '会话、工具和长期记忆', 27, 'blue'),
    'input-memory': previewMemoryGraphNode('book:input-memory', 'book', '输入法记忆与上下文', '完整输入段、App 来源和闪电联想边界', 12, 'green'),
  } as const;
  const fallback = previewMemoryGraphNode(
    `${kind}:${entityId || 'preview'}`,
    kind,
    entityId || '预览记忆',
    '本地记忆关系',
    0,
    'gray',
  );
  const entity = catalog[entityId as keyof typeof catalog] ?? fallback;
  const related = kind === 'tag'
    ? catalog['memory-quality']
    : kind === 'book'
      ? catalog['input-method']
      : catalog['agent-runtime'];
  const connectionEdge = kind === 'tag'
    ? previewMemoryGraphEdge(`entity-edge:${entityId}`, 'tagRelation', String(entity.id), String(related.id), 'related_to', 0.88, 6)
    : kind === 'book'
      ? previewMemoryGraphEdge(`entity-edge:${entityId}`, 'groupMember', String(related.id), String(entity.id), 'contains', 0.9, 1)
      : previewMemoryGraphEdge(`entity-edge:${entityId}`, 'groupMember', String(entity.id), String(related.id), 'contains', 0.9, 1);
  const members = kind === 'group'
    ? [catalog['input-boundary'], catalog['memory-quality']].map((node) => ({
        node,
        edge: previewMemoryGraphEdge(`entity-member:${String(node.id)}`, 'groupMember', String(entity.id), String(node.id), 'contains', 1, 1),
      }))
    : [];
  return {
    schemaVersion: 'rag-ime.memory-entity.v1',
    ok: true,
    settingsRevision: 'settings:preview',
    runtimeRevision: 7,
    kind,
    entityId: entityId || 'preview',
    entityRevision: `sha256:${'b'.repeat(64)}`,
    project: 'wisdom-weasel-rag-ime',
    entity,
    attributes: {
      type: kind === 'group' ? 'semantic' : kind === 'book' ? 'topic' : 'concept',
      aliases: kind === 'tag' && entityId === 'memory-quality' ? ['记忆治理'] : [],
      tags: kind === 'book' ? ['输入封口', '记忆质量'] : [],
    },
    connections: { items: [{ node: related, edge: connectionEdge }], nextCursor: '', limit: 40, hasMore: false },
    members: { items: members, nextCursor: '', limit: 40, hasMore: false },
    limits: { connectionsLimit: 40, membersLimit: 40 },
  };
}

function previewMemoryCurationStatus(status: string): Record<string, unknown> {
  return {
    ok: true,
    policy: 'review',
    autoApply: false,
    pendingDraftCount: status === 'draft' ? 1 : 0,
    runs: [{ runId: 'memory_book_preview', status, diffCount: 3, createdAtMs: Date.now() - 180_000 }],
  };
}

function previewMemoryCurationRun(
  selections: Map<number, boolean>,
  status: string,
): Record<string, unknown> {
  const changes = [
    ['upsert_memory_atom', '更新记忆原子', '输入封口边界', 'Backspace 修改缓冲区，Enter 或切换 App 后才写入完整段落。', 18],
    ['merge_semantic_tag', '合并标签', '合并输入法同义标签', '保留清晰名称和别名，移除传输层标签。', 11],
    ['supersede_memory', '归档噪声', '隔离旧 Rime 碎片', '未封口单词和短片段不再参与 Agent 上下文或长期记忆。', 4_887],
  ].map(([operation, operationLabel, title, detail, sourceCount], index) => {
    const diffId = index + 1;
    const selected = selections.get(diffId) === true;
    return {
      diffId,
      operation,
      operationLabel,
      status: status === 'draft' ? (selected ? 'approved' : 'rejected') : status === 'rolled_back' ? 'rolled_back' : 'applied',
      selected,
      title,
      detail,
      sourceCount,
    };
  });
  return {
    ok: true,
    stale: false,
    canApply: status === 'draft' && changes.some((change) => change.selected),
    canRollback: status === 'applied',
    run: {
      runId: 'memory_book_preview',
      status,
      createdAtMs: Date.now() - 180_000,
      diffCount: changes.length,
      pendingDiffCount: status === 'draft' ? changes.filter((change) => change.selected).length : 0,
      changes,
    },
  };
}

function previewMemoryApplyPreview(): Record<string, unknown> {
  return {
    schemaVersion: 'rag-ime.management-work-preview.v1',
    ok: true,
    previewToken: 'preview-memory-curation',
    pathId: 'knowledge.database.apply',
    payloadSha256: `sha256:${'d'.repeat(64)}`,
    expectedRevision: { runtimeRevision: 7, subjectRevision: 'memory_book_preview' },
    expiresAtMs: Date.now() + 60_000,
    requiredConfirm: 'apply',
    summary: {
      title: '应用所选记忆更新',
      items: ['只写入已勾选的整理建议', '重建本地记忆检索索引'],
      risk: 'R2',
    },
  };
}

function previewMemoryWorkReceipt(pathId: string, rollbackAvailable: boolean): Record<string, unknown> {
  return {
    schemaVersion: 'rag-ime.management-work-receipt.v1',
    ok: true,
    receiptId: pathId.endsWith('rollback') ? 'receipt-memory-curation-rollback' : 'receipt-memory-curation',
    pathId,
    payloadSha256: `sha256:${'d'.repeat(64)}`,
    appliedAtMs: Date.now(),
    auditId: 17,
    rollbackAvailable,
    rollbackToken: rollbackAvailable ? 'rollback-memory-curation' : '',
    rollbackAuthority: { runId: 'memory_book_preview' },
    restartComponents: [],
    result: { status: pathId.endsWith('rollback') ? 'rolled_back' : 'applied' },
  };
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

function previewContextTrace(
  sessionId: string,
  traceId: string,
): Record<string, unknown> {
  const createdAtMs = Date.now() - 18_000;
  const nodes = [
    previewContextNode('node:1:input', 1, 'input', '当前消息', 'user', '收到本轮用户输入', 126, 32, 0, createdAtMs),
    previewContextNode('node:2:session', 2, 'session', '角色与会话', 'gateway', '装配角色、模型和会话策略', 860, 215, 2, createdAtMs + 2),
    previewContextNode('node:3:tools', 3, 'tools', '工具目录', 'gateway', '按权限暴露本轮可用工具', 1_420, 355, 4, createdAtMs + 4),
    previewContextNode('node:4:inbox', 4, 'inbox', '异步上下文', 'context_runtime', '没有等待注入的异步结果', 0, 0, 1, createdAtMs + 5, 'omitted'),
    previewContextNode('node:5:runtime-request', 5, 'runtime_request', 'Pi Runtime 请求', 'gateway', '已形成受限运行时请求', 2_406, 602, 7, createdAtMs + 7),
  ];
  return {
    schemaVersion: 'rag-ime.agent-context-trace.v1',
    traceId,
    sessionId,
    turnId: 'turn-preview',
    sourceKind: 'user',
    status: 'accepted',
    finalFingerprint: 'sha256:0123456789abcdef',
    nodes,
    edges: [
      { source: nodes[0].nodeId, target: nodes[1].nodeId },
      { source: nodes[1].nodeId, target: nodes[2].nodeId },
      { source: nodes[1].nodeId, target: nodes[3].nodeId },
      { source: nodes[2].nodeId, target: nodes[4].nodeId },
      { source: nodes[3].nodeId, target: nodes[4].nodeId },
    ],
    createdAtMs,
    updatedAtMs: createdAtMs + 7,
  };
}

function previewDebugContext(sessionId: string, turnId: string): Record<string, unknown> {
  const now = Date.now() - 17_000;
  return {
    schemaVersion: 'rag-ime.pi-debug-context-response.v1',
    sessionId,
    turnId,
    available: true,
    transient: true,
    context: {
      schemaVersion: 'rag-ime.pi-debug-context.v1',
      sessionId,
      turnId,
      clientMessageId: 'preview-message',
      capturedAtMs: now,
      updatedAtMs: now + 120,
      prompt: '<rag-ime-user-query>检查当前上下文与缓存命中情况</rag-ime-user-query>',
      systemPrompt: 'You are the local RagIme coding agent. Follow the current role and workspace policy.',
      systemPromptOptions: { cwd: '/Volumes/work/project', enabledTools: ['read', 'grep'] },
      model: { provider: 'openai', id: 'gpt-5.2', name: 'GPT-5.2', api: 'responses' },
      activeTools: ['read', 'grep', 'memory_search'],
      toolSchemas: [
        { name: 'read', description: 'Read a local file', parameters: { type: 'object', properties: { path: { type: 'string' } } } },
        { name: 'memory_search', description: 'Search approved memory', parameters: { type: 'object', properties: { query: { type: 'string' } } } },
      ],
      contextWindows: [{
        index: 1,
        capturedAtMs: now + 80,
        messages: [
          { role: 'user', content: [{ type: 'text', text: '检查当前上下文与缓存命中情况' }] },
          { role: 'assistant', content: [{ type: 'text', text: '我会读取真实运行时指标。' }] },
        ],
      }],
      providerRequests: [{
        index: 1,
        capturedAtMs: now + 120,
        payload: {
          model: 'gpt-5.2',
          instructions: 'You are the local RagIme coding agent.',
          input: [{ role: 'user', content: [{ type: 'input_text', text: '检查当前上下文与缓存命中情况' }] }],
          tools: [{ type: 'function', name: 'memory_search' }],
        },
      }],
    },
    telemetry: {
      schemaVersion: 'rag-ime.agent-session-telemetry.v1',
      model: { provider: 'openai', id: 'gpt-5.2', name: 'GPT-5.2' },
      context: { tokens: 98_560, contextWindow: 128_000, percent: 77, remainingTokens: 29_440, compactAtTokens: 111_616, tokensUntilCompact: 13_056, reserveTokens: 16_384, keepRecentTokens: 20_000, autoCompactEnabled: true },
      cumulativeUsage: { input: 7_200, output: 3_562, cacheRead: 64_800, cacheWrite: 0, totalTokens: 75_562 },
      latestUsage: { input: 1_400, output: 562, cacheRead: 12_600, cacheWrite: 0, totalTokens: 14_562 },
      latestCacheHitPercent: 90,
      isCompacting: false,
      compactionCount: 2,
      updatedAtMs: now + 120,
    },
  };
}

function previewContextNode(
  nodeId: string,
  ordinal: number,
  stage: string,
  label: string,
  sourceKind: string,
  summary: string,
  charCount: number,
  tokenEstimate: number,
  durationMs: number,
  createdAtMs: number,
  disposition: 'included' | 'omitted' = 'included',
): Record<string, unknown> {
  return {
    nodeId,
    ordinal,
    stage,
    label,
    sourceKind,
    disposition,
    summary,
    charCount,
    tokenEstimate,
    durationMs,
    fingerprint: charCount ? `sha256:${String(ordinal).repeat(16)}` : '',
    reason: disposition === 'omitted' ? '本轮没有可投递项目' : '',
    metadata: stage === 'tools' ? { toolCount: 18 } : {},
    createdAtMs,
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
      roomKind: 'collaboration',
      avatar: 'briefcase',
      description: '验证责任交接、流式投影与多端控制面板',
      routingPolicy: 'moderator',
      moderatorParticipantId: 'participant-zhiyou',
      activeTopicId: 'topic-preview',
      workspaceRoots: ['/Volumes/work/wisdom-weasel-rag-ime'],
      topics: [{
        schemaVersion: 'rag-ime.agent-room-topic.v1',
        id: 'topic-preview',
        roomId,
        title: '网关升级',
        summary: '保持 Pi Session 独立，以 WorkItem 责任账本完成协作闭环。',
        status: 'active',
        ordinal: 0,
        createdAtMs: now,
        updatedAtMs: now,
      }],
      artifacts: [],
      workItems: [{
        schemaVersion: 'rag-ime.agent-room-work-item.v1',
        id: 'room-work:preview',
        roomId,
        topicId: 'topic-preview',
        rootTurnId: `${roomId}:turn-1`,
        rootWorkId: 'room-work:preview',
        parentWorkId: '',
        objective: '核对多端网关回放与责任闭环',
        expectedOutput: '测试证据和风险说明',
        acceptanceCriteria: ['目标回合接受后才转移 owner', '交付经过协调者验收'],
        accountableParticipantId: 'participant-zhiyou',
        currentOwnerParticipantId: 'participant-hermes',
        offeredToParticipantId: '',
        createdByParticipantId: 'participant-zhiyou',
        clientMessageId: 'preview-assignment',
        state: 'review',
        depth: 1,
        revision: 1,
        resultSummary: '已完成回放游标与公平队列测试。',
        artifactRefs: [],
        evidenceRefs: ['test:room-replay'],
        blocker: {},
        acceptedTurnId: 'turn:preview-worker',
        createdAtMs: now + 2,
        updatedAtMs: now + 7,
        completedAtMs: null,
      }],
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
    collaborationRole: ordinal === 0 ? 'coordinator' : 'researcher',
    status: 'active',
    ordinal,
    createdAtMs: 1,
    lastSpokeAtMs: null,
  };
}
