import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { StubControlTransport } from '@/test/stub-control-transport';
import { AgentFeature } from './index';
import { previewAgentEvents, previewAgentSnapshot, previewModelCatalog, previewPersonas, previewSessions } from './preview-data';
import { SessionRail } from './sessions/SessionRail';
import { useAgentLiveStore } from './state/live-store';
import { AgentTurn } from './timeline/AgentTimeline';
import type { ModelCatalog } from './types';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  for (const session of previewSessions) useAgentLiveStore.getState().clear(session.id);
  useAgentLiveStore.getState().clear('session-history');
});

describe('Agent experience', () => {
  it('makes the full session row clickable', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<TooltipProvider><SessionRail sessions={previewSessions} selectedId="session-preview" loading={false} onSelect={onSelect} onCreate={() => {}} /></TooltipProvider>);
    await user.click(screen.getByRole('button', { name: /记忆整理/ }));
    expect(onSelect).toHaveBeenCalledWith('session-memory');
  });

  it('renders one persona avatar and one activity container per assistant turn without raw payloads', async () => {
    const sessionId = 'session-preview';
    const snapshot = previewAgentSnapshot(sessionId);
    useAgentLiveStore.getState().hydrateSnapshot(sessionId, snapshot);
    const events = previewAgentEvents(sessionId);
    events[1] = { ...events[1]!, payload: { ...events[1]!.payload, rawSecret: '{"token":"do-not-render"}' } };
    useAgentLiveStore.getState().applyEvents(sessionId, events);
    const turnId = `${sessionId}:turn-architecture`;
    render(<TooltipProvider><AgentTurn sessionId={sessionId} turnId={turnId} persona={previewPersonas[0]} onApprovalDecision={() => {}} /></TooltipProvider>);
    expect(screen.getAllByAltText('智鼬·此刻头像')).toHaveLength(1);
    expect(document.querySelectorAll('.agent-activity')).toHaveLength(1);
    expect(document.querySelector('.agent-user-message')).toBeInTheDocument();
    expect(screen.queryByText(/do-not-render/)).not.toBeInTheDocument();
    expect(document.querySelector('.agent-assistant-message')).toHaveTextContent('三条 Lane 已经收束到同一个');
  });

  it('keeps hydrated legacy history replies beside their user turns', () => {
    const sessionId = 'session-history';
    useAgentLiveStore.getState().hydrate(sessionId, {
      lastSequence: 4,
      resumeToken: `${sessionId}:4`,
      items: [
        historyMessage(sessionId, 'assistant-orphan', 'assistant', '上一段回复'),
        historyMessage(sessionId, 'user-one', 'user', '第一个问题'),
        historyMessage(sessionId, 'assistant-one-a', 'assistant', '第一段回复'),
        historyMessage(sessionId, 'assistant-one-b', 'assistant', '第一段补充'),
        historyMessage(sessionId, 'user-two', 'user', '第二个问题'),
        historyMessage(sessionId, 'user-three', 'user', '第三个问题'),
        historyMessage(sessionId, 'assistant-three', 'assistant', '第三段回复'),
      ],
    });

    const projection = useAgentLiveStore.getState().projections[sessionId];
    expect(projection.turnOrder).toEqual([
      'history:assistant-orphan',
      'history:user-one',
      'history:user-two',
      'history:user-three',
    ]);
    expect(projection.turnsById['history:user-one'].messageIds).toEqual([
      'user-one',
      'assistant-one-a',
      'assistant-one-b',
    ]);
    expect(projection.turnsById['history:user-two'].messageIds).toEqual(['user-two']);

    render(
      <TooltipProvider>
        <AgentTurn
          sessionId={sessionId}
          turnId="history:user-three"
          persona={previewPersonas[0]}
          onApprovalDecision={() => {}}
        />
      </TooltipProvider>,
    );
    expect(screen.getByText('第三个问题')).toBeInTheDocument();
    expect(screen.getByText('第三段回复')).toBeInTheDocument();
  });

  it('sends through the allowlisted prompt path', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await user.type(composer, '检查 reducer 边界');
    await user.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true));
    const prompt = transport.requests.find((call) => call.request.pathId === 'agent.session.prompt');
    expect(prompt?.request.params).toEqual({ sessionId: 'session-preview' });
    expect(prompt?.request.body).toMatchObject({ message: '检查 reducer 边界' });
  });

  it('imports managed images for the current session before sending mediaIds', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    await screen.findByRole('textbox', { name: '消息' });
    await user.click(screen.getByRole('button', { name: '添加附件' }));
    expect(transport.filePickCalls).toEqual([{
      accepts: ['image/png', 'image/jpeg', 'image/gif', 'image/webp'],
      multiple: true,
      purpose: 'attachment',
      sessionId: 'session-preview',
      maxFiles: 8,
    }]);
    await user.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true));
    const prompt = transport.requests.find((call) => call.request.pathId === 'agent.session.prompt');
    expect(prompt?.request.body).toMatchObject({ attachments: ['media_fixture_attachment_01'] });
  });

  it('pastes supported clipboard images into the managed attachment chain', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await screen.findByRole('button', { name: /模型：/ });
    const image = new File([new Uint8Array([137, 80, 78, 71])], 'clipboard.png', { type: 'image/png' });

    fireEvent.paste(composer, {
      clipboardData: {
        files: [],
        items: [{ kind: 'file', getAsFile: () => image }],
      },
    });

    await waitFor(() => expect(transport.imagePasteCalls).toHaveLength(1));
    expect(transport.imagePasteCalls[0]).toMatchObject({ sessionId: 'session-preview' });
    expect(await screen.findByText('screen.png')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true));
    const prompt = transport.requests.find((call) => call.request.pathId === 'agent.session.prompt');
    expect(prompt?.request.body).toMatchObject({ attachments: ['media_fixture_attachment_01'] });
  });

  it('leaves ordinary text paste alone and reports unsupported or oversized image files', async () => {
    const transport = featureTransport();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });

    expect(fireEvent.paste(composer, { clipboardData: { files: [], getData: () => '普通文本' } })).toBe(true);
    expect(transport.imagePasteCalls).toHaveLength(0);

    const unsupported = new File(['bad'], 'diagram.svg', { type: 'image/svg+xml' });
    expect(fireEvent.paste(composer, { clipboardData: { files: [unsupported] } })).toBe(false);
    expect(await screen.findByRole('alert')).toHaveTextContent('仅支持 PNG、JPEG、GIF 和 WebP');
    expect(transport.imagePasteCalls).toHaveLength(0);

    const oversized = new File(['x'], 'huge.webp', { type: 'image/webp' });
    Object.defineProperty(oversized, 'size', { value: 20 * 1024 * 1024 + 1 });
    fireEvent.paste(composer, { clipboardData: { files: [oversized] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('必须小于 20 MiB');
    expect(transport.imagePasteCalls).toHaveLength(0);
  });

  it('loads the complete tool catalog and writes an explicit tool intent without faking execution', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const trigger = await screen.findByRole('button', { name: '受控工具：13 个' });

    await user.click(trigger);
    expect(screen.getByRole('button', { name: /控制中心概览/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /受控命令/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /控制中心概览/ }));

    expect(screen.getByRole('textbox', { name: '消息' })).toHaveValue('请使用 ime_overview（控制中心概览）：');
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('keeps Sessions and roles usable when the tool catalog is unavailable', async () => {
    const transport = featureTransport(previewModelCatalog('session-preview'), () => {
      throw new Error('tools unavailable');
    });
    renderAgent(transport);

    expect(await screen.findByRole('button', { name: /控制中心迁移/ })).toBeInTheDocument();
    expect(await screen.findByRole('textbox', { name: '消息' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '受控工具：0 个' })).toBeDisabled();
  });

  it('uses the runtime selected id and defaults new Sessions to 5.6 Luna', async () => {
    const transport = featureTransport(lunaModelCatalog());
    const user = userEvent.setup();
    renderAgent(transport);

    expect(await screen.findByRole('button', { name: /模型：GPT-5.6 Luna/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '新建 Session' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.sessions.create')).toBe(true));
    const create = transport.requests.find((call) => call.request.pathId === 'agent.sessions.create');
    expect(create?.request.body).toMatchObject({ modelProfile: 'gpt/gpt-5.6-luna' });
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.model.select')).toBe(false);
  });

  it('starts with the session rail closed on mobile and closes it after selection', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })));
    const user = userEvent.setup();
    renderAgent(featureTransport());
    const feature = document.querySelector('.agent-feature');
    expect(feature).toHaveAttribute('data-rail-open', 'false');

    await user.click(screen.getByRole('button', { name: '展开 Sessions' }));
    expect(feature).toHaveAttribute('data-rail-open', 'true');
    await user.click(await screen.findByRole('button', { name: /记忆整理/ }));
    expect(feature).toHaveAttribute('data-rail-open', 'false');
  });

  it('releases the session rail grid column when collapsed on desktop', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })));
    const user = userEvent.setup();
    const { container } = render(
      <MemoryRouter initialEntries={['/agent']}>
        <ControlTransportProvider transport={featureTransport()}>
          <TooltipProvider>
            <div className="shell-route-stage"><AgentFeature /></div>
          </TooltipProvider>
        </ControlTransportProvider>
      </MemoryRouter>,
    );
    const feature = container.querySelector<HTMLElement>('main.agent-feature');
    expect(feature).toHaveAttribute('data-rail-open', 'true');

    await user.click(screen.getByRole('button', { name: '收起 Sessions' }));

    expect(feature).toHaveAttribute('data-rail-open', 'false');
    expect(getComputedStyle(feature!).gridTemplateColumns).toBe('0 minmax(0, 1fr)');
  });

  it('selects the Session requested by the roles route handoff', async () => {
    const transport = featureTransport();
    renderAgent(transport, '/agent?session=session-memory');

    expect(await screen.findByRole('button', { name: /记忆整理/ })).toHaveAttribute('aria-current', 'true');
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.snapshot',
        params: { sessionId: 'session-memory' },
      }),
    })));
  });

  it('does not substitute preview Sessions or Personas in the native host', async () => {
    const transport = new StubControlTransport('native', {
      'agent.sessions.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: [] },
      'agent.tools.list': { ok: true, items: [] },
    });
    render(
      <MemoryRouter initialEntries={['/agent']}>
        <ControlTransportProvider transport={transport}>
          <TooltipProvider><AgentFeature /></TooltipProvider>
        </ControlTransportProvider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(transport.requests.map((request) => request.pathId)).toEqual(
      expect.arrayContaining(['agent.sessions.list', 'agent.roles.list']),
    ));
    expect(screen.getByText('0 个连续对话')).toBeInTheDocument();
    expect(screen.queryByText('控制中心迁移')).not.toBeInTheDocument();
    expect(screen.queryByText('记忆整理')).not.toBeInTheDocument();
  });
});

function renderAgent(transport: MockControlTransport, initialEntry = '/agent') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ControlTransportProvider transport={transport}>
        <TooltipProvider><AgentFeature /></TooltipProvider>
      </ControlTransportProvider>
    </MemoryRouter>,
  );
}

function featureTransport(
  modelCatalog = previewModelCatalog('session-preview'),
  toolRoute: unknown = { ok: true, items: toolCatalog() },
): MockControlTransport {
  return new MockControlTransport({
    pickedFiles: [{
      id: 'media_fixture_attachment_01',
      name: 'screen.png',
      mimeType: 'image/png',
      byteSize: 68,
      sessionId: 'session-preview',
      sha256: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
    }],
    importedFiles: [{
      id: 'media_fixture_attachment_01',
      name: 'screen.png',
      mimeType: 'image/png',
      byteSize: 68,
      sessionId: 'session-preview',
      sha256: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
    }],
    routes: {
      'agent.sessions.list': { ok: true, items: previewSessions },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.tools.list': toolRoute,
      'agent.session.snapshot': previewAgentSnapshot('session-preview'),
      'agent.session.models': modelCatalog,
      'agent.session.prompt': { ok: true },
      'agent.sessions.create': { ok: true },
      'agent.session.compact': { ok: true },
      'agent.session.abort': { ok: true },
      'agent.session.mode.update': { ok: true },
      'agent.session.model.select': { ok: true },
      'agent.session.thinking.select': { ok: true },
      'agent.approval.decide': { ok: true },
    },
  });
}

function lunaModelCatalog(): ModelCatalog {
  return {
    schemaVersion: 'rag-ime.agent-model-catalog.v1',
    ok: true,
    sessionId: 'session-preview',
    selected: { provider: 'gpt', id: 'gpt-5.6-luna', modelId: 'codex-mini-latest', name: 'GPT-5.6 Luna' },
    thinkingLevel: 'medium',
    providers: [{
      id: 'gpt',
      displayName: 'GPT',
      models: [
        modelFixture('codex-mini-latest', 'Codex Mini'),
        modelFixture('gpt-5.6-luna', 'GPT-5.6 Luna'),
      ],
    }],
  };
}

function modelFixture(id: string, name: string) {
  return { provider: 'gpt', id, name, api: 'responses', reasoning: true, thinkingLevels: ['off', 'medium'] as ['off', 'medium'], supportsImages: true, contextWindow: 100_000, maxTokens: 32_000 };
}

function toolCatalog() {
  const tools = [
    ['ime_overview', '控制中心概览', 'overview'],
    ['ime_input', '输入法', 'input'],
    ['ime_voice', '语音输入', 'voice'],
    ['ime_planning', '规划与任务', 'planning'],
    ['ime_memory', '记忆与工具书', 'memory'],
    ['ime_knowledge', '知识检索', 'knowledge'],
    ['ime_models', '模型', 'models'],
    ['ime_runtime', '诊断与运行时', 'runtime'],
    ['ime_configuration', '历史与配置', 'configuration'],
    ['ime_agents', '多 Agent 协作', 'agents'],
    ['workspace_list', '工作区浏览', 'workspace'],
    ['workspace_read', '工作区读取', 'workspace'],
    ['workspace_shell', '受控命令', 'workspace'],
  ] as const;
  return tools.map(([id, displayName, category]) => ({
    schemaVersion: 'rag-ime.control-tool-manifest.v1',
    id,
    domain: category,
    displayName,
    description: `${displayName}真实能力`,
    category,
    riskLevel: id === 'workspace_shell' ? 'R2' : 'R0',
    operationRisks: { status: id === 'workspace_shell' ? 'R2' : 'R0' },
    sessionModes: id.startsWith('workspace_') ? ['coordinator'] : ['assistant', 'coordinator'],
    operations: ['status'],
    resultPresentation: 'tool_result',
    availability: 'online',
    version: '1',
  }));
}

function historyMessage(
  sessionId: string,
  id: string,
  role: 'user' | 'assistant',
  text: string,
) {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id,
    sessionId,
    turnId: 'history',
    role,
    status: 'completed',
    blocks: [{
      id: `${id}:text`,
      type: 'text',
      status: 'completed',
      presentationKind: 'markdown',
      data: { text },
    }],
    attachments: [],
    citations: [],
    createdAtMs: 100,
    completedAtMs: 101,
  };
}
