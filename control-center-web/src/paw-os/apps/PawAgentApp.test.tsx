import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import type { ControlRequest } from '@/platform/transport';
import { PawOsAppSurfaceProvider, PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import { PawAgentApp } from './PawAgentApp';

vi.mock('./PawSessionWorkspace', () => ({
  PawSessionWorkspace: () => <div>Session 工作区</div>,
}));
vi.mock('./PawRoomWorkspace', () => ({
  PawRoomWorkspace: ({ recordId }: { recordId: string }) => <div>Room 工作区 · {recordId}</div>,
}));
vi.mock('@/features/roles', () => ({ RolesFeature: () => <div>角色工作区</div> }));

afterEach(() => {
  cleanup();
  delete window.pawBrowserHost;
});

describe('PAWOS Agent App', () => {
  it('uses one rail for Sessions and Rooms and starts on the central new-work composer', async () => {
    renderAgent();

    expect(await screen.findByRole('heading', { name: '交给 Agent 一件事。' })).toBeInTheDocument();
    const rail = screen.getByRole('complementary', { name: 'Agent 工作记录' });
    expect(within(rail).getByText('工作记录')).toBeInTheDocument();
    expect(within(rail).getByRole('button', { name: /^发布检查/ })).toBeInTheDocument();
    expect(within(rail).getByRole('button', { name: /迁移作战室/ })).toBeInTheDocument();
    expect(within(rail).getByText('Session')).toBeInTheDocument();
    expect(within(rail).getByText('Room')).toBeInTheDocument();
    expect(rail.querySelector('[data-paw-app-icon]')).not.toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Session' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Room' })).not.toBeChecked();
  });

  it('exposes the rail relationship and returns focus when Escape closes it', async () => {
    const user = userEvent.setup();
    renderAgent();

    const toggle = await screen.findByRole('button', { name: '打开工作记录' });
    const rail = screen.getByRole('complementary', { name: 'Agent 工作记录' });
    expect(rail).toHaveAttribute('id', 'paw-agent-work-records');
    expect(toggle).toHaveAttribute('aria-controls', 'paw-agent-work-records');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await user.click(toggle);
    expect(screen.getByRole('button', { name: '收起工作记录' })).toHaveAttribute('aria-expanded', 'true');
    await user.keyboard('{Escape}');

    expect(screen.getByRole('button', { name: '打开工作记录' })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: '打开工作记录' })).toHaveFocus();
  });

  it('returns focus to the owning chip when Escape closes an anchored composer menu', async () => {
    const user = userEvent.setup();
    renderAgent();

    const chip = await screen.findByRole('button', { name: /按风险确认/ });
    await user.click(chip);
    expect(screen.getByRole('menu')).toBeInTheDocument();
    await user.tab();
    expect(chip).not.toHaveFocus();
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(chip).toHaveFocus();
  });

  it('keeps the containing window identity aligned when the same Agent window moves between Room and Session', async () => {
    const bindAgentMain = vi.fn();
    const transport = createTransport();
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ControlTransportProvider transport={transport}>
          <TooltipProvider>
            <PawOsDesktopProvider bindAgentMain={bindAgentMain} openWindow={() => undefined}>
              <PawOsAppSurfaceProvider appId="agent" height={720} width={1_080} windowId="agent">
                <PawAgentApp />
              </PawOsAppSurfaceProvider>
            </PawOsDesktopProvider>
          </TooltipProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await screen.findByRole('heading', { name: '交给 Agent 一件事。' });
    await waitFor(() => expect(bindAgentMain).toHaveBeenCalledWith('agent'));
    const rail = screen.getByRole('complementary', { name: 'Agent 工作记录' });

    await user.click(within(rail).getByRole('button', { name: /^迁移作战室/ }));
    await waitFor(() => expect(bindAgentMain).toHaveBeenCalledWith('agent', expect.objectContaining({
      kind: 'room', id: 'room-old', title: '迁移作战室',
    })));

    await user.click(within(rail).getByRole('button', { name: /^发布检查/ }));
    await waitFor(() => expect(bindAgentMain).toHaveBeenLastCalledWith('agent', {
      kind: 'session', id: 'session-old', title: '发布检查',
    }));
  });

  it('hydrates untouched composer defaults from the production configuration authority', async () => {
    renderAgent(createTransport({
      modelCatalog: modelCatalog(),
      preferencesHandler: () => preferenceSettings({
        modelReference: 'gpt/gpt-5.6-sol',
        thinkingLevel: 'max',
        executionMode: 'read_only',
      }),
    }));

    expect(await screen.findByRole('button', { name: /GPT-5\.6 Sol · Max/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /只读/ })).toBeInTheDocument();
  });

  it('does not let late authority hydration overwrite a composer choice already made by the user', async () => {
    const settings = deferred<unknown>();
    const user = userEvent.setup();
    renderAgent(createTransport({ modelCatalog: modelCatalog(), preferencesHandler: () => settings.promise }));

    await user.click(await screen.findByRole('button', { name: /GPT-5\.6 Luna/ }));
    await user.click(await screen.findByRole('menuitemradio', { name: 'GPT-5.6 Sol' }));
    settings.resolve(preferenceSettings({
      modelReference: 'gpt/gpt-5.6-terra',
      thinkingLevel: 'high',
      executionMode: 'read_only',
    }));

    await waitFor(() => expect(screen.getByRole('button', { name: /只读/ })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /GPT-5\.6 Sol/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /GPT-5\.6 Terra · High/ })).not.toBeInTheDocument();
  });

  it('shows an explicit configuration recovery action when composer defaults cannot be read', async () => {
    renderAgent(createTransport({ preferencesHandler: () => { throw new Error('配置服务暂时不可用'); } }));

    expect(await screen.findByRole('alert')).toHaveTextContent('配置服务暂时不可用');
    expect(screen.getByRole('button', { name: '重新读取' })).toBeInTheDocument();
  });

  it('reports only real model-catalog facts on the home footer instead of a runtime connectivity claim', async () => {
    const empty = renderAgent();
    await screen.findByRole('heading', { name: '交给 Agent 一件事。' });
    expect(screen.queryByText(/Pi Runtime/)).not.toBeInTheDocument();
    expect(screen.queryByText(/个可用模型/)).not.toBeInTheDocument();
    empty.unmount();

    renderAgent(createTransport({ modelCatalog: modelCatalog() }));
    expect(await screen.findByText('3 个可用模型')).toBeInTheDocument();
    expect(screen.getByText(/默认模型 gpt-5\.6-luna/)).toBeInTheDocument();
    expect(screen.queryByText(/Pi Runtime/)).not.toBeInTheDocument();
  });

  it('reflects the selected permission risk on the composer chip state dot', async () => {
    const user = userEvent.setup();
    renderAgent();

    const chip = await screen.findByRole('button', { name: /按风险确认/ });
    expect(chip.querySelector('.mini-dot')).toHaveAttribute('data-execution-mode', 'per_action');

    await user.click(chip);
    await user.click(await screen.findByRole('menuitemradio', { name: /^只读/ }));
    expect(screen.getByRole('button', { name: /只读/ }).querySelector('.mini-dot'))
      .toHaveAttribute('data-execution-mode', 'read_only');
  });

  it('orders 继续工作 by real recency instead of catalog list position', async () => {
    renderAgent(createTransport({
      sessions: [
        { id: 's-a', title: '最旧的检查', mode: 'coordinator', status: 'idle', updatedAtMs: 1, workspaceRoots: ['/work/paw'], messageCount: 1, lastMessagePreview: '' },
        { id: 's-b', title: '较旧的检查', mode: 'coordinator', status: 'idle', updatedAtMs: 2, workspaceRoots: ['/work/paw'], messageCount: 1, lastMessagePreview: '' },
        { id: 's-c', title: '次新的检查', mode: 'coordinator', status: 'idle', updatedAtMs: 4, workspaceRoots: ['/work/paw'], messageCount: 1, lastMessagePreview: '' },
        { id: 's-d', title: '最新的检查', mode: 'coordinator', status: 'idle', updatedAtMs: 9, workspaceRoots: ['/work/paw'], messageCount: 1, lastMessagePreview: '' },
      ],
    }));

    const recent = (await screen.findByRole('heading', { name: '继续工作' })).parentElement!;
    expect(within(recent).getByRole('button', { name: /最新的检查/ })).toBeInTheDocument();
    expect(within(recent).queryByRole('button', { name: /最旧的检查/ })).not.toBeInTheDocument();
  });

  it('creates a Session and sends the first prompt from the same composer', async () => {
    const transport = createTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    const composer = await screen.findByRole('textbox', { name: '描述你想完成的工作' });
    await user.type(composer, '检查发布门禁并给出结论');
    await user.click(screen.getByRole('button', { name: '开始 Session' }));

    await waitFor(() => expect(transport.requests.map(({ request }) => request.pathId)).toEqual(
      expect.arrayContaining(['agent.sessions.create', 'agent.session.prompt']),
    ));
    const prompt = transport.requests.find(({ request }) => request.pathId === 'agent.session.prompt')?.request;
    expect(prompt?.params).toEqual({ sessionId: 'session-new' });
    expect(prompt?.body).toMatchObject({ message: '检查发布门禁并给出结论' });
    expect(await screen.findByText('Session 工作区')).toBeInTheDocument();
  });

  it('opens the Session before a slow first-prompt receipt settles', async () => {
    const prompt = deferred<unknown>();
    const transport = createTransport({ promptHandler: () => prompt.promise });
    const user = userEvent.setup();
    renderAgent(transport);

    await user.type(await screen.findByRole('textbox', { name: '描述你想完成的工作' }), '立即进入工作现场');
    await user.click(screen.getByRole('button', { name: '开始 Session' }));

    await waitFor(() => expect(screen.getByText('Session 工作区')).toBeInTheDocument());
    expect(transport.requests.map(({ request }) => request.pathId)).toContain('agent.session.prompt');
    prompt.resolve({ ok: true });
  });

  it('admits the first prompt without waiting for model configuration', async () => {
    const modelSelect = deferred<unknown>();
    const transport = createTransport({
      modelHandler: () => modelSelect.promise,
      modelCatalog: {
        providers: [{ id: 'gpt', models: [{ id: 'gpt-5.6-luna', name: 'GPT-5.6 Luna', thinkingLevels: ['off'] }] }],
        selected: { provider: 'gpt', id: 'gpt-5.6-luna' },
      },
    });
    const user = userEvent.setup();
    renderAgent(transport);

    await user.type(await screen.findByRole('textbox', { name: '描述你想完成的工作' }), '不要等待模型配置');
    await user.click(screen.getByRole('button', { name: '开始 Session' }));

    await waitFor(() => expect(screen.getByText('Session 工作区')).toBeInTheDocument());
    await waitFor(() => expect(transport.requests.some(({ request }) => request.pathId === 'agent.session.prompt')).toBe(true));
    modelSelect.resolve({ ok: true });
  });

  it('keeps the optimistic Session visible when a catalog refresh is stale', async () => {
    const transport = createTransport({ staleCatalogAfterCreate: true });
    const user = userEvent.setup();
    renderAgent(transport);

    await user.type(await screen.findByRole('textbox', { name: '描述你想完成的工作' }), '保持目录一致');
    await user.click(screen.getByRole('button', { name: '开始 Session' }));

    const rail = screen.getByRole('complementary', { name: 'Agent 工作记录' });
    await waitFor(() => expect(within(rail).getByText('保持目录一致')).toBeInTheDocument());
  });

  it('hydrates a new-work draft from the PAWOS route and reacts to a later deep link', async () => {
    const transport = createTransport();
    const view = renderAgent(transport, { initialRoute: '/agent?draft=先检查发布门禁' });

    expect(await screen.findByRole('textbox', { name: '描述你想完成的工作' })).toHaveValue('先检查发布门禁');

    view.rerender(agentTree(transport, { initialRoute: '/agent?draft=再检查安装状态' }));
    expect(await screen.findByRole('textbox', { name: '描述你想完成的工作' })).toHaveValue('再检查安装状态');
  });

  it('accepts the sessionId compatibility deep link without returning to new work', async () => {
    renderAgent(createTransport(), { initialRoute: '/agent?sessionId=session-old' });

    expect(await screen.findByText('Session 工作区')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '交给 Agent 一件事。' })).not.toBeInTheDocument();
  });

  it('archives, reveals, restores, and deletes Sessions through the real lifecycle routes', async () => {
    const transport = createTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: '更多“发布检查”操作' }));
    await user.click(await screen.findByRole('menuitem', { name: '归档 Session' }));
    await waitFor(() => expect(transport.requests.some(({ request }) => request.pathId === 'agent.session.archive')).toBe(true));
    expect(screen.queryByRole('button', { name: /^发布检查/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '工作记录选项' }));
    await user.click(await screen.findByRole('menuitemcheckbox', { name: '显示已归档 Session' }));
    await user.click(await screen.findByRole('button', { name: '更多“发布检查”操作' }));
    await user.click(await screen.findByRole('menuitem', { name: '恢复 Session' }));

    await user.click(await screen.findByRole('button', { name: '更多“发布检查”操作' }));
    await user.click(await screen.findByRole('menuitem', { name: '删除 Session' }));
    const dialog = await screen.findByRole('dialog', { name: /删除“发布检查”/ });
    await user.click(within(dialog).getByRole('button', { name: '删除' }));

    await waitFor(() => expect(transport.requests.some(({ request }) => request.pathId === 'agent.session.delete')).toBe(true));
    expect(screen.queryByRole('button', { name: /^发布检查/ })).not.toBeInTheDocument();
  });

  it('states the consequence of Session next to the composer and previews Room partners on switch', async () => {
    const user = userEvent.setup();
    renderAgent();

    const composer = await screen.findByRole('textbox', { name: '描述你想完成的工作' });
    const briefId = composer.getAttribute('aria-describedby') ?? '';
    expect(briefId).not.toBe('');
    const sessionBrief = document.getElementById(briefId);
    expect(sessionBrief).toHaveTextContent('一位 Agent 在同一条时间线里完成这件事');

    await user.click(screen.getByRole('radio', { name: 'Room' }));
    const roomBrief = within(document.getElementById(briefId) as HTMLElement);
    expect(roomBrief.getByText('将加入的伙伴')).toBeInTheDocument();
    expect(roomBrief.getByText('构建者')).toBeInTheDocument();
    expect(roomBrief.getByText('协调')).toBeInTheDocument();
    expect(roomBrief.getByText('审阅者')).toBeInTheDocument();
    expect(roomBrief.getByText('审阅')).toBeInTheDocument();
  });

  it('blocks a Room start with the truthful reason when fewer than two partners exist', async () => {
    const user = userEvent.setup();
    renderAgent(createTransport({ personas: [persona('builder', '构建者')] }));

    await user.type(await screen.findByRole('textbox', { name: '描述你想完成的工作' }), '只有一位伙伴');
    await user.click(screen.getByRole('radio', { name: 'Room' }));

    expect(screen.getByText('Room 需要至少 2 位可用伙伴，当前只有 1 位，暂时无法开始。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始 Room' })).toBeDisabled();
  });

  it('projects the real catalog state in the Home footer and recovers with one reload', async () => {
    let modelCalls = 0;
    const transport = createTransport({
      modelCatalog: () => {
        modelCalls += 1;
        if (modelCalls === 1) throw new Error('目录服务不可用');
        return modelCatalog();
      },
    });
    const user = userEvent.setup();
    renderAgent(transport);

    expect(await screen.findByRole('status')).toHaveTextContent('部分 Agent 目录暂时不可用。');
    expect(screen.queryByText(/Pi Runtime 已连接/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '重新读取目录' }));

    expect(await screen.findByText('3 个可用模型')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('states the archived Session state on its revealed rail row', async () => {
    const transport = createTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: '更多“发布检查”操作' }));
    await user.click(await screen.findByRole('menuitem', { name: '归档 Session' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: /^发布检查/ })).not.toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: '工作记录选项' }));
    await user.click(await screen.findByRole('menuitemcheckbox', { name: '显示已归档 Session' }));

    const rail = screen.getByRole('complementary', { name: 'Agent 工作记录' });
    const row = await within(rail).findByRole('button', { name: /^发布检查/ });
    expect(row).toHaveTextContent('已归档 · paw ·');
  });

  it('switches the same entry to Room and creates it with selected partners', async () => {
    const transport = createTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('radio', { name: 'Room' }));
    await user.type(screen.getByRole('textbox', { name: '描述你想完成的工作' }), '并行检查前端与后端');
    await user.click(screen.getByRole('button', { name: '开始 Room' }));

    await waitFor(() => expect(transport.requests.map(({ request }) => request.pathId)).toEqual(
      expect.arrayContaining(['agent.rooms.create', 'agent.room.message']),
    ));
    const create = transport.requests.find(({ request }) => request.pathId === 'agent.rooms.create')?.request;
    expect(create?.body).toMatchObject({
      roomKind: 'collaboration',
      participants: expect.arrayContaining([
        expect.objectContaining({ roleId: 'builder' }),
        expect.objectContaining({ roleId: 'reviewer' }),
      ]),
    });
    expect(await screen.findByText('Room 工作区 · room-new')).toBeInTheDocument();
  });

  it('selects a new workspace with the installed Electron host before starting a Room', async () => {
    const transport = createTransport();
    Object.defineProperty(transport, 'pickFiles', { configurable: true, value: undefined });
    const pickWorkspaceDirectory = vi.fn(async () => ({
      name: 'paw-natural',
      path: '/work/paw-natural',
    }));
    window.pawBrowserHost = {
      kind: 'electron-webview',
      partition: 'persist:paw-browser',
      pickWorkspaceDirectory,
    } as unknown as NonNullable<typeof window.pawBrowserHost>;
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: 'work/paw' }));
    await user.click(await screen.findByRole('button', { name: '浏览其他目录…' }));
    await waitFor(() => expect(pickWorkspaceDirectory).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: 'work/paw-natural' })).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'Room' }));
    await user.type(screen.getByRole('textbox', { name: '描述你想完成的工作' }), '从自然目标开始');
    await user.click(screen.getByRole('button', { name: '开始 Room' }));

    await waitFor(() => expect(transport.requests.some(({ request }) => request.pathId === 'agent.rooms.create')).toBe(true));
    const create = transport.requests.find(({ request }) => request.pathId === 'agent.rooms.create')?.request;
    expect(create?.body).toMatchObject({ workspaceRoots: ['/work/paw-natural'] });
  });

  it('opens the Room and its optimistic first message before a slow Room receipt settles', async () => {
    const roomMessage = deferred<unknown>();
    const transport = createTransport({ roomMessageHandler: () => roomMessage.promise });
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('radio', { name: 'Room' }));
    await user.type(screen.getByRole('textbox', { name: '描述你想完成的工作' }), '立即进入 Room 现场');
    await user.click(screen.getByRole('button', { name: '开始 Room' }));

    await waitFor(() => expect(screen.getByText('Room 工作区 · room-new')).toBeInTheDocument());
    expect(transport.requests.map(({ request }) => request.pathId)).toContain('agent.room.message');
    roomMessage.resolve({ ok: true });
  });
});

type MockSessionSummary = {
  id: string;
  title: string;
  mode: string;
  status: string;
  updatedAtMs: number;
  workspaceRoots: string[];
  messageCount: number;
  lastMessagePreview: string;
};

function agentTree(transport = createTransport(), props: { initialRoute?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>
          <PawAgentApp {...props} />
        </TooltipProvider>
      </ControlTransportProvider>
    </QueryClientProvider>
  );
}

function renderAgent(transport = createTransport(), props: { initialRoute?: string } = {}) {
  return render(agentTree(transport, props));
}

function createTransport(options: {
  promptHandler?: () => Promise<unknown>;
  modelHandler?: () => Promise<unknown>;
  modelCatalog?: unknown;
  personas?: unknown[];
  roomMessageHandler?: () => Promise<unknown>;
  staleCatalogAfterCreate?: boolean;
  preferencesHandler?: () => unknown | Promise<unknown>;
  sessions?: MockSessionSummary[];
} = {}) {
  let sessions: MockSessionSummary[] = options.sessions ?? [{
    id: 'session-old', title: '发布检查', mode: 'coordinator', status: 'idle', updatedAtMs: 2,
    workspaceRoots: ['/work/paw'], messageCount: 3, lastMessagePreview: '检查构建结果',
  }];
  let rooms = [{
    id: 'room-old', title: '迁移作战室', status: 'active', roomKind: 'collaboration',
    routingPolicy: 'parallel', moderatorParticipantId: 'p1', updatedAtMs: 3,
    workspaceRoots: ['/work/paw'], participants: [
      { id: 'p1', sessionId: 's1', roleId: 'builder', roleVersion: '1', displayName: '构建者', status: 'active', ordinal: 0 },
      { id: 'p2', sessionId: 's2', roleId: 'reviewer', roleVersion: '1', displayName: '审阅者', status: 'active', ordinal: 1 },
    ],
  }];
  return new MockControlTransport({
    routes: {
      'agent.sessions.list': (request: ControlRequest) => ({
        ok: true,
        items: request.query?.includeArchived ? sessions : sessions.filter((session) => session.status !== 'archived'),
      }),
      'agent.rooms.list': () => ({ ok: true, items: rooms }),
      'agent.roles.list': {
        ok: true,
        items: options.personas ?? [persona('builder', '构建者'), persona('reviewer', '审阅者')],
      },
      'agent.role.models': options.modelCatalog ?? { providers: [], selected: {} },
      'configuration.settings': options.preferencesHandler ?? preferenceSettings({}),
      'agent.sessions.create': (request: ControlRequest) => {
        const body = request.body as Record<string, unknown>;
        const created = { ...sessions[0], id: 'session-new', title: body.title as string, updatedAtMs: 4 };
        if (!options.staleCatalogAfterCreate) sessions = [created];
        return { ok: true, session: created };
      },
      'agent.session.prompt': options.promptHandler ?? { ok: true },
      'agent.session.archive': (request: ControlRequest) => {
        const sessionId = String(request.params?.sessionId ?? '');
        const archived = Boolean((request.body as Record<string, unknown>)?.archived);
        sessions = sessions.map((session) => session.id === sessionId
          ? { ...session, status: archived ? 'archived' : 'idle', updatedAtMs: session.updatedAtMs + 1 }
          : session);
        return { ok: true };
      },
      'agent.session.delete': (request: ControlRequest) => {
        const sessionId = String(request.params?.sessionId ?? '');
        sessions = sessions.filter((session) => session.id !== sessionId);
        return { ok: true };
      },
      'agent.session.model.select': options.modelHandler ?? { ok: true },
      'agent.session.thinking.select': { ok: true },
      'agent.rooms.create': (request: ControlRequest) => {
        const body = request.body as Record<string, unknown>;
        const created = {
          ...rooms[0], id: 'room-new', title: body.title as string,
          participants: body.participants, updatedAtMs: 5,
        };
        rooms = [created as typeof rooms[number]];
        return { ok: true, room: created };
      },
      'agent.room.message': options.roomMessageHandler ?? { ok: true },
    },
  });
}

function modelCatalog() {
  return {
    providers: [{
      id: 'gpt',
      models: [
        { provider: 'gpt', id: 'gpt-5.6-luna', name: 'GPT-5.6 Luna', thinkingLevels: ['off', 'high', 'max'] },
        { provider: 'gpt', id: 'gpt-5.6-sol', name: 'GPT-5.6 Sol', thinkingLevels: ['off', 'high', 'max'] },
        { provider: 'gpt', id: 'gpt-5.6-terra', name: 'GPT-5.6 Terra', thinkingLevels: ['off', 'high', 'max'] },
      ],
    }],
    selected: { provider: 'gpt', id: 'gpt-5.6-luna' },
  };
}

function preferenceSettings(overrides: Partial<{
  modelReference: string;
  thinkingLevel: string;
  executionMode: string;
}>) {
  return {
    ok: true,
    settings: {
      agent: {
        defaults: {
          modelReference: 'inherit',
          thinkingLevel: 'high',
          executionMode: 'per_action',
          ...overrides,
        },
      },
    },
    runtimeConfig: { runtimeRevision: 7 },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function persona(roleId: string, displayName: string) {
  return {
    schemaVersion: 'rag-ime.agent-persona.v1', roleId, version: '1', displayName,
    tagline: `${displayName}伙伴`, description: '', selectableModes: ['assistant', 'coordinator'],
    defaults: { mode: 'coordinator', executionMode: 'per_action', modelPolicy: 'inherit', thinkingLevel: 'high', toolProfileVersion: 'control-center-v1', toolAllowlistMode: 'profile' },
    runtimeCharacteristics: { isDefault: false, canReadWorkspace: true, canWriteWorkspace: true, canUseTools: true },
    visualProfile: { accentToken: 'violet', avatar: 'bot' },
    content: { systemPrompt: '', boundaries: [], firstMessage: '' }, status: 'active', createdAtMs: 1, updatedAtMs: 1,
  };
}
