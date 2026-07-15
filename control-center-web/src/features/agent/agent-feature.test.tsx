import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { StubControlTransport } from '@/test/stub-control-transport';
import type { ControlTransport } from '@/platform/transport';
import { AgentFeature } from './index';
import { previewAgentEvents, previewAgentSnapshot, previewModelCatalog, previewPersonas, previewSessions } from './preview-data';
import { SessionRail } from './sessions/SessionRail';
import { useAgentLiveStore } from './state/live-store';
import { AgentTurn } from './timeline/AgentTimeline';
import type { ModelCatalog, ThinkingLevel } from './types';

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
    expect(projection.turnsById['history:user-one'].status).toBe('completed');
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

  it('renders a rejected Pi prompt once with a public recovery message', async () => {
    const transport = featureTransport(
      previewModelCatalog('session-preview'),
      { ok: true, items: toolCatalog() },
      { ok: true, items: previewSessions },
      () => { throw new Error('404 Model "gpt-5.6-luna" is not supported by any configured account in this group'); },
    );
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });

    await user.type(composer, '你是谁');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const failedTurn = Object.values(projection.turnsById).find((turn) => turn.failure);
    expect(failedTurn?.failure).toBe('当前模型不可用，请切换模型后重试。');
    expect(document.querySelector('.agent-conversation__header [role="alert"]')).not.toBeInTheDocument();
    expect(screen.queryByText(/not supported by any configured account/i)).not.toBeInTheDocument();
  });

  it('uses the Pi RPC command catalog and supports keyboard and pointer selection', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.commands')).toBe(true));

    await user.type(composer, '/re');
    expect(screen.getByRole('option', { name: /\/review/ })).toBeInTheDocument();
    expect(screen.queryByText('/memory')).not.toBeInTheDocument();
    await user.keyboard('{Enter}');
    expect(composer).toHaveValue('/review ');

    await user.clear(composer);
    await user.type(composer, '/');
    await user.keyboard('{ArrowDown}{Enter}');
    expect(composer).toHaveValue('/compact ');

    await user.clear(composer);
    await user.type(composer, '/skill');
    await user.click(screen.getByRole('option', { name: /\/skill:browser/ }));
    expect(composer).toHaveValue('/skill:browser ');

    await user.clear(composer);
    await user.type(composer, '/');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox', { name: '命令面板' })).not.toBeInTheDocument();
  });

  it('accepts a planning handoff as an editable composer draft', async () => {
    const transport = featureTransport();
    renderAgent(transport, `/agent?draft=${encodeURIComponent('请整理今天的真实规划')}`);

    expect(await screen.findByRole('textbox', { name: '消息' })).toHaveValue('请整理今天的真实规划');
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('pastes supported clipboard images into the managed attachment chain', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ });
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

  it('imports a selected image through the native managed attachment picker', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    const attachmentButton = await screen.findByRole('button', { name: '添加图片' });
    expect(attachmentButton).toBeVisible();
    expect(attachmentButton).toBeEnabled();
    await user.click(attachmentButton);

    expect(transport.filePickCalls).toEqual([{
      accepts: ['image/png', 'image/jpeg', 'image/gif', 'image/webp'],
      multiple: true,
      purpose: 'attachment',
      sessionId: 'session-preview',
      maxFiles: 8,
    }]);
    expect(await screen.findByText('screen.png')).toBeInTheDocument();
  });

  it('leaves ordinary text paste alone and reports unsupported or oversized image files', async () => {
    const transport = featureTransport();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ });
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

  it('asks the native host to read the system pasteboard when WebKit hides the image File', async () => {
    const transport = featureTransport();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ });
    expect(screen.getByRole('button', { name: '添加图片' })).toBeEnabled();

    expect(fireEvent.paste(composer, {
      clipboardData: {
        files: [],
        items: [{ kind: 'file', type: 'image/png', getAsFile: () => null }],
      },
    })).toBe(false);
    await waitFor(() => expect(transport.imagePasteCalls).toHaveLength(1));
    expect(transport.imagePasteCalls[0]).toEqual({ sessionId: 'session-preview', maxFiles: 8 });
  });

  it('falls back to the native pasteboard when WebKit exposes neither File nor item metadata', async () => {
    const transport = featureTransport();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ });

    expect(fireEvent.paste(composer, {
      clipboardData: { files: [], items: [], getData: () => '' },
    })).toBe(false);

    await waitFor(() => expect(transport.imagePasteCalls).toEqual([
      { sessionId: 'session-preview', maxFiles: 8 },
    ]));
  });

  it('disables image selection and explains paste rejection for a Pi text-only model', async () => {
    const catalog = previewModelCatalog('session-preview');
    catalog.selected = { provider: 'deepseek', id: 'deepseek-v4' };
    const transport = featureTransport(catalog);
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });

    await screen.findByRole('button', { name: /模型：DeepSeek V4/ });
    expect(screen.getByRole('button', { name: '当前模型不支持图片' })).toBeDisabled();

    const image = new File(['png'], 'clipboard.png', { type: 'image/png' });
    expect(fireEvent.paste(composer, { clipboardData: { files: [image] } })).toBe(false);
    expect(await screen.findByRole('alert')).toHaveTextContent('当前模型不支持图片');
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

    expect(screen.getByRole('textbox', { name: '消息' })).toHaveValue('请使用“控制中心概览”：');
    expect(screen.queryByText('ime_overview')).not.toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('keeps Sessions and roles usable when the tool catalog is unavailable', async () => {
    const transport = featureTransport(previewModelCatalog('session-preview'), () => {
      throw new Error('tools unavailable');
    });
    renderAgent(transport);

    expect(await screen.findByRole('button', { name: /控制中心迁移/ })).toBeInTheDocument();
    expect(await screen.findByRole('textbox', { name: '消息' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '受控工具目录加载失败' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '受控工具目录加载失败' })).toHaveTextContent('工具 · 未加载');
  });

  it('opens the backend active conversation instead of a newer empty Session', async () => {
    const emptySession = { ...previewSessions[0], id: 'session-empty', title: '刚创建的空对话', messageCount: 0, lastMessagePreview: '' };
    const activeSession = { ...previewSessions[1], id: 'session-active', title: '仍在继续的对话', messageCount: 12, lastMessagePreview: '最近的助手回复' };
    const transport = featureTransport(
      previewModelCatalog('session-active'),
      { ok: true, items: toolCatalog() },
      { ok: true, activeSessionId: activeSession.id, items: [emptySession, activeSession] },
    );
    renderAgent(transport);

    expect(await screen.findByRole('button', { name: /仍在继续的对话/ })).toHaveAttribute('aria-current', 'true');
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.snapshot',
        params: { sessionId: 'session-active' },
      }),
    })));
  });

  it('does not let an empty runtime-active Session hide the most recent conversation', async () => {
    const emptyActive = { ...previewSessions[0], id: 'session-empty-active', title: '空白活动对话', messageCount: 0, lastMessagePreview: '' };
    const meaningful = { ...previewSessions[1], id: 'session-meaningful', title: '继续昨天的对话', messageCount: 6, lastMessagePreview: '已保留回复' };
    const transport = featureTransport(
      previewModelCatalog('session-meaningful'),
      { ok: true, items: toolCatalog() },
      { ok: true, activeSessionId: emptyActive.id, items: [emptyActive, meaningful] },
    );
    renderAgent(transport);

    expect(await screen.findByRole('button', { name: /继续昨天的对话/ })).toHaveAttribute('aria-current', 'true');
  });

  it('keeps persisted conversation visible when the model catalog fails', async () => {
    const transport = productionTransport({
      'agent.session.models': () => { throw new Error('provider probe failed'); },
    });
    renderAgent(transport);

    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.messageOrder).toHaveLength(4));
    expect(useAgentLiveStore.getState().projections['session-preview']?.turnOrder).toHaveLength(2);
    expect(await screen.findByRole('alert')).toHaveTextContent('模型目录暂时不可用，对话记录仍可查看');
  });

  it('keeps persisted conversation visible when the Pi command catalog fails', async () => {
    const transport = productionTransport({
      'agent.session.commands': () => { throw new Error('commands unavailable'); },
    });
    renderAgent(transport);

    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.messageOrder).toHaveLength(4));
    expect(useAgentLiveStore.getState().projections['session-preview']?.turnOrder).toHaveLength(2);
    expect(await screen.findByRole('alert')).toHaveTextContent('Pi 命令暂时不可用，仍可直接发送消息');
  });

  it('rehydrates persisted user and assistant blocks after a page remount', async () => {
    const first = productionTransport();
    const rendered = renderAgent(first);
    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.messageOrder).toHaveLength(4));

    rendered.unmount();
    useAgentLiveStore.getState().clear('session-preview');
    renderAgent(productionTransport());

    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.messageOrder).toHaveLength(4));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const persistedMessages = Object.values(projection?.messagesById ?? {});
    expect(persistedMessages.some((message) => message.role === 'user'
      && message.blocks.some((block) => String(block.data.text).includes('把迁移进度按真实代码链整理一下')))).toBe(true);
    expect(persistedMessages.some((message) => message.role === 'assistant'
      && message.blocks.some((block) => String(block.data.text).includes('三条 Lane 已经收束到同一个')))).toBe(true);
  });

  it('uses the Pi runtime selection and lets the Luna persona choose its timeline model', async () => {
    const transport = featureTransport(lunaModelCatalog());
    const user = userEvent.setup();
    renderAgent(transport);

    expect(await screen.findByRole('button', { name: /模型：GPT-5.6 Luna/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '新建对话' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.sessions.create')).toBe(true));
    const create = transport.requests.find((call) => call.request.pathId === 'agent.sessions.create');
    expect(create?.request.body).toMatchObject({ roleId: 'hermes-v1', roleVersion: '1' });
    expect(create?.request.body).not.toHaveProperty('modelProfile');
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.model.select')).toBe(false);
  });

  it('renders Pi-provided Max reasoning and sends xhigh without inventing levels', async () => {
    const transport = featureTransport(lunaModelCatalog());
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: /模型：GPT-5.6 Luna/ }));
    const lunaDetails = screen.getByText('GPT-5.6 Luna', { selector: 'summary' }).closest('details');
    expect(lunaDetails).not.toBeNull();
    for (const level of ['关闭', '最小', '低', '中', '高', 'Max']) {
      expect(within(lunaDetails!).getByRole('button', { name: level })).toBeInTheDocument();
    }
    const max = within(lunaDetails!).getByRole('button', { name: 'Max' });
    await user.click(max);

    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.session.thinking.select'
      && typeof call.request.body === 'object'
      && call.request.body !== null
      && !Array.isArray(call.request.body)
      && call.request.body.level === 'xhigh'
    ))).toBe(true));
  });

  it('does not show Max when the Pi model catalog omits xhigh', async () => {
    const catalog = lunaModelCatalog();
    catalog.providers[0]!.models[1] = modelFixture(
      'gpt-5.6-luna',
      'GPT-5.6 Luna',
      ['off', 'minimal', 'low', 'medium', 'high'],
    );
    const user = userEvent.setup();
    renderAgent(featureTransport(catalog));

    await user.click(await screen.findByRole('button', { name: /模型：GPT-5.6 Luna/ }));
    expect(screen.queryByRole('button', { name: 'Max' })).not.toBeInTheDocument();
  });

  it('uses the real model and thinking selection routes then reloads Pi state', async () => {
    const transport = featureTransport(lunaModelCatalog());
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: /模型：GPT-5.6 Luna/ }));
    const codexDetails = screen.getByText('Codex Mini').closest('details');
    expect(codexDetails).not.toBeNull();
    codexDetails!.open = true;
    await user.click(within(codexDetails!).getByRole('button', { name: '中' }));

    await waitFor(() => expect(transport.requests).toEqual(expect.arrayContaining([
      expect.objectContaining({ request: expect.objectContaining({
        pathId: 'agent.session.model.select',
        body: { provider: 'gpt', modelId: 'codex-mini-latest' },
      }) }),
      expect.objectContaining({ request: expect.objectContaining({
        pathId: 'agent.session.thinking.select',
        body: { level: 'medium' },
      }) }),
    ])));
    expect(transport.requests.filter((call) => call.request.pathId === 'agent.session.models')).toHaveLength(2);
  });

  it('starts with the session rail closed on mobile and closes it after selection', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })));
    const user = userEvent.setup();
    renderAgent(featureTransport());
    const feature = document.querySelector('.agent-feature');
    expect(feature).toHaveAttribute('data-rail-open', 'false');

    await user.click(screen.getByRole('button', { name: '展开对话列表' }));
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

    await user.click(screen.getByRole('button', { name: '收起对话列表' }));

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

function renderAgent(transport: ControlTransport, initialEntry = '/agent') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ControlTransportProvider transport={transport}>
        <TooltipProvider><AgentFeature /></TooltipProvider>
      </ControlTransportProvider>
    </MemoryRouter>,
  );
}

function featureTransport(
  modelCatalog: unknown = previewModelCatalog('session-preview'),
  toolRoute: unknown = { ok: true, items: toolCatalog() },
  sessionRoute: unknown = { ok: true, items: previewSessions },
  promptRoute: unknown = { ok: true },
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
      'agent.sessions.list': sessionRoute,
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.tools.list': toolRoute,
      'agent.session.snapshot': previewAgentSnapshot('session-preview'),
      'agent.session.models': modelCatalog,
      'agent.session.commands': commandCatalog(),
      'agent.session.prompt': promptRoute,
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

function productionTransport(
  overrides: Partial<Record<string, unknown>> = {},
): StubControlTransport {
  return new StubControlTransport('native', {
    'agent.sessions.list': { ok: true, activeSessionId: 'session-preview', items: previewSessions },
    'agent.roles.list': { ok: true, items: previewPersonas },
    'agent.tools.list': { ok: true, items: toolCatalog() },
    'agent.session.snapshot': previewAgentSnapshot('session-preview'),
    'agent.session.models': previewModelCatalog('session-preview'),
    'agent.session.commands': commandCatalog(),
    ...overrides,
  } as ConstructorParameters<typeof StubControlTransport>[1]);
}

function commandCatalog() {
  return {
    schemaVersion: 'rag-ime.agent-command-catalog.v1',
    ok: true,
    sessionId: 'session-preview',
    runtimeAvailable: true,
    items: [
      { name: 'review', invocation: '/review', description: '审阅当前改动', source: 'extension' },
      { name: 'plan', invocation: '/plan', description: '运行规划模板', source: 'prompt' },
      { name: 'skill:browser', invocation: '/skill:browser', description: '调用浏览器技能', source: 'skill' },
    ],
  };
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
        modelFixture('gpt-5.6-luna', 'GPT-5.6 Luna', ['off', 'minimal', 'low', 'medium', 'high', 'xhigh']),
      ],
    }],
  };
}

function modelFixture(id: string, name: string, thinkingLevels: ThinkingLevel[] = ['off', 'medium']) {
  return { provider: 'gpt', id, name, api: 'responses', reasoning: true, thinkingLevels: thinkingLevels as [ThinkingLevel, ...ThinkingLevel[]], supportsImages: true, contextWindow: 100_000, maxTokens: 32_000 };
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
