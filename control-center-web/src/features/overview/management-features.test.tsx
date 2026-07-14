import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import type { ComponentType } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { ConfigurationFeature } from '@/features/configuration';
import { DiagnosticsFeature } from '@/features/diagnostics';
import { HistoryFeature } from '@/features/history';
import { InputMethodFeature } from '@/features/input-method';
import { KnowledgeFeature } from '@/features/knowledge';
import { MemoryFeature } from '@/features/memory';
import { PlanningFeature } from '@/features/planning';
import { PluginsFeature } from '@/features/plugins';
import { VoiceFeature } from '@/features/voice';
import type { ControlPathId } from '@/platform/routes';
import { MockControlTransport, type MockRouteHandler } from '@/test/mock-transport';
import { OverviewFeature } from './index';

const now = 1_752_499_200_000;

const routeFixtures: Partial<Record<ControlPathId, MockRouteHandler>> = {
  'system.health': { ok: true, status: 'ready' },
  'overview.get': {
    ok: true,
    profile: '标准模式',
    aiPaused: false,
    components: {
      inputMethod: { id: 'inputMethod', ok: true, status: 'ready', detail: '已选择' },
      predictor: { id: 'predictor', ok: true, status: 'ready', detail: 'MLX resident' },
    },
    memory: { eventCount: 18, memoryItemCount: 14, memoryBookCount: 4, memoryAtomCount: 10, retrievalDocCount: 22, pendingCompileEvents: 2 },
    lastPrediction: { visibleCandidate: '继续完成控制中心迁移', triggerReason: 'post_commit', contextSource: 'foreground', totalLatencyMs: 124, sourceTypes: ['model', 'rag'] },
  },
  'agent.runtime.get': {
    schemaVersion: 'rag-ime.agent-runtime.v1',
    enabled: true,
    managed: true,
    status: 'ready',
    driverId: 'pi-managed',
    runtimeKind: 'pi',
    runtimeVersion: 'test',
    piVersion: 'test',
    idleTimeoutSeconds: 900,
    activeSessionId: null,
    lastError: '',
    capabilities: {},
  },
  'agent.tools.list': {
    ok: true,
    items: [{ id: 'memory.search', displayName: '记忆检索', description: '搜索本地记忆', domain: 'memory', category: 'memory', riskLevel: 'R0', operations: ['search'], availability: 'online' }],
  },
  'input.source.get': {
    ok: true,
    inputSourceId: 'im.rime.inputmethod.Squirrel.Rime',
    typingReady: true,
    selected: true,
    readinessState: 'ready',
    readinessMessage: 'foreground typing ready',
  },
  'planning.dashboard': {
    ok: true,
    runtimeRevision: 7,
    date: '2026-07-14',
    plan: { intention: '完成 Web 迁移', notes: '保持接口边界', reflection: '', project: 'wisdom-weasel-rag-ime' },
    tasks: [{ id: 'task-1', title: '完成管理页', detail: '运行测试并截图', status: 'in_progress', source: 'manual' }],
    goals: [{ id: 'goal-1', title: '统一控制中心', detail: 'React 可见端', status: 'active', targetDate: '2026-07-15' }],
    pendingCompletionSuggestions: [],
    recentDetectedCompletion: null,
    summary: { taskCount: 1, openTaskCount: 1, completedTaskCount: 0, goalCount: 1, progress: 0 },
    assistant: { message: '先完成可验证的迁移闭环。', tone: 'focus' },
  },
  'memory.summary': { ok: true, eventCount: 18, memoryItemCount: 14, memoryBookCount: 4, memoryAtomCount: 10, pendingCompileEvents: 2 },
  'memory.pages': {
    ok: true,
    items: [{ id: 'book-1', title: '控制中心迁移', summary: 'React 页面与受控 API', source: 'user', status: 'active' }],
    nextCursor: '',
    limit: 50,
  },
  'history.page': {
    ok: true,
    items: [{ id: 81, createdAtMs: now, source: 'rime_commit', app: 'TextEdit', project: 'wisdom-weasel-rag-ime', textPreview: '完成了...', textChars: 6, contextHash: 'sha256:test' }],
    nextCursor: '',
    limit: 50,
    rawTextVisible: false,
  },
  'knowledge.routeStatus': {
    ok: true,
    deepseekReady: true,
    notion: { submitConfigured: true, pollConfigured: false, ready: false, pollMode: 'worker' },
  },
  'knowledge.status': { ok: false, status: 'missing', error: 'sessionId is required', evidence: [], sources: [] },
  'diagnostics.runtime': {
    ok: true,
    components: {
      sidecar: { id: 'sidecar', ok: true, status: 'ready', detail: '运行中' },
      sqlite: { id: 'sqlite', ok: true, status: 'ready', detail: 'FTS5 ready' },
    },
  },
  'diagnostics.predictor': { ok: true, predictor: { status: 'ready', provider: 'mlx', model: 'qwen3-0.6b' } },
  'diagnostics.models': { ok: true, schemaVersion: 'rag-ime.models-status.v3', predictor: { status: 'ready', provider: 'mlx' }, activeRagRoute: { remoteReady: true, skipReason: '' } },
  'configuration.settings': {
    ok: true,
    settingsRevision: 'settings-test',
    runtimeRevision: 4,
    settings: {
      interaction: { postCommit: { enabled: true } },
      voice: { provider: 'native-streaming', tokenConfigured: true, hotkey: 'middle-mouse', hotwordsEnabled: false },
      security: { apiToken: 'top-secret-must-not-render' },
    },
  },
  'configuration.schema': {
    ok: true,
    schemaVersion: 'rag-ime.settings-schema.v1',
    sections: [
      {
        id: 'interaction',
        label: '交互',
        fields: [
          { key: 'interaction.postCommit.enabled', type: 'boolean', label: '提交后预测', description: '提交后调度助手候选', applyMode: 'live', expert: false },
          { key: 'security.apiToken', type: 'secret', label: 'API Token', description: 'Keychain secret', applyMode: 'restart_sidecar', expert: false },
        ],
      },
      { id: 'display', label: '显示', fields: [] },
      { id: 'activeRag', label: 'RAG', fields: [] },
      { id: 'pinyin', label: '拼音', fields: [] },
      { id: 'voice', label: '语音', fields: [] },
    ],
  },
};

const pages: readonly [string, ComponentType, string, ControlPathId][] = [
  ['overview', OverviewFeature, '今日概览', 'overview.get'],
  ['input', InputMethodFeature, '输入法', 'input.source.get'],
  ['plugins', PluginsFeature, '插件与工具', 'agent.tools.list'],
  ['voice', VoiceFeature, '语音输入', 'configuration.settings'],
  ['planning', PlanningFeature, '规划', 'planning.dashboard'],
  ['memory', MemoryFeature, '记忆', 'memory.pages'],
  ['knowledge', KnowledgeFeature, '知识库', 'knowledge.routeStatus'],
  ['history', HistoryFeature, '输入历史', 'history.page'],
  ['diagnostics', DiagnosticsFeature, '诊断与修复', 'diagnostics.runtime'],
  ['configuration', ConfigurationFeature, '配置与迁移', 'configuration.schema'],
];

afterEach(cleanup);

describe('management features', () => {
  it.each(pages)('%s renders from its allowlisted read boundary', async (_id, Feature, heading, expectedPathId) => {
    const transport = renderFeature(Feature);
    expect(await screen.findByRole('heading', { name: heading, level: 1 })).toBeInTheDocument();
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === expectedPathId)).toBe(true));
    expect(screen.queryByText('top-secret-must-not-render')).not.toBeInTheDocument();
  });

  it('fails closed when the management WorkContract capability is absent', async () => {
    renderFeature(PlanningFeature);
    await screen.findByRole('heading', { name: '规划', level: 1 });
    const unsupported = await screen.findAllByRole('button', { name: '后端暂不支持' });
    expect(unsupported.length).toBeGreaterThan(0);
    expect(unsupported.every((button) => button.hasAttribute('disabled'))).toBe(true);
    expect(screen.queryByText('演练 / 未执行')).not.toBeInTheDocument();
  });
});

function renderFeature(Feature: ComponentType): MockControlTransport {
  const transport = new MockControlTransport({ routes: routeFixtures });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}>
            <Feature />
          </QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
  return transport;
}
