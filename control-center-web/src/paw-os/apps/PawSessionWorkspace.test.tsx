import { forwardRef, type Key, type ReactNode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { AgentProjectionState } from '@/contracts/agent-reducer';
import { parseAgentEvent } from '@/contracts/validators';
import { SessionSubagentPanel } from '@/features/agent/delegation/SessionSubagentPanel';
import { useAgentLiveStore } from '@/features/agent/state/live-store';
import type { SessionSummary } from '@/features/agent/types';
import { StubControlTransport } from '@/test/stub-control-transport';
import agentMigratedCss from '../styles/paw-os-agent-migrated-v1.css?raw';
import { PawWindowFrame } from '../shell/PawWindowLayer';
import { PawSessionWorkspace } from './PawSessionWorkspace';

/* jsdom gives every row zero height, so the real virtualizer would keep the
   transcript empty and no timeline assertion here would mean anything. */
vi.mock('react-virtuoso', () => ({
  Virtuoso: forwardRef(function MockVirtuoso({
    components,
    computeItemKey,
    context,
    data,
    itemContent,
    scrollerRef,
  }: {
    components?: { Header?: (props: { context?: unknown }) => ReactNode; Footer?: () => ReactNode };
    computeItemKey?: (index: number, item: string) => Key;
    context?: unknown;
    data: string[];
    itemContent: (index: number, item: string) => ReactNode;
    scrollerRef?: (scroller: HTMLElement | Window | null) => void;
  }) {
    const Header = components?.Header;
    const Footer = components?.Footer;
    return (
      <div data-testid="virtuoso-list" ref={(node) => scrollerRef?.(node)}>
        {Header ? <Header context={context} /> : null}
        {data.map((item, index) => (
          <div key={computeItemKey?.(index, item) ?? index}>{itemContent(index, item)}</div>
        ))}
        {Footer ? <Footer /> : null}
      </div>
    );
  }),
}));

afterEach(cleanup);

describe('PAWOS Agent Session structural migration', () => {
  it.each([375, 360])('projects one complete Session chrome into a %ipx production window', async (width) => {
    render(
      <ControlTransportProvider transport={createPreviewTransport()}>
        <TooltipProvider>
          <PawWindowFrame
            active
            appId="agent"
            bounds={{ x: 0, y: 0, width, height: 720 }}
            onBoundsCommit={() => undefined}
            onClose={() => undefined}
            onFocus={() => undefined}
            onMinimize={() => undefined}
            onToggleMaximize={() => undefined}
            title="完整迁移"
            windowChrome="agent-session"
            windowId={`agent-${width}`}
            zIndex={10}
          >
            <PawSessionWorkspace
              record={liveSession()}
              recordId="session-live"
              onNewWork={vi.fn()}
              onSessionCreated={vi.fn()}
              onSessionUpdated={vi.fn()}
            />
          </PawWindowFrame>
        </TooltipProvider>
      </ControlTransportProvider>,
    );

    await screen.findByRole('textbox', { name: '消息' });
    const window = screen.getByLabelText('完整迁移窗口');
    const titlebar = window.querySelector('.paw-window-titlebar') as HTMLElement;
    expect(titlebar.querySelectorAll('.paw-session-workspace__header')).toHaveLength(1);
    expect(within(titlebar).getByText('完整迁移')).toBeInTheDocument();
    expect(titlebar.querySelector('.paw-session-workspace__identity')).not.toBeInTheDocument();
    expect(window.querySelector('.paw-window-body .paw-session-workspace__header')).toBeNull();
    expect(within(titlebar).getByRole('button', { name: '对话' })).toBeInTheDocument();
    expect(within(titlebar).getByRole('button', { name: 'Agent 轨迹' })).toBeInTheDocument();
    expect(within(titlebar).getByRole('button', { name: '星空' })).toBeInTheDocument();
    expect(within(titlebar).getByRole('button', { name: 'Session 工具' })).toBeInTheDocument();
    const sessionHeader = titlebar.querySelector('.paw-session-workspace__header') as HTMLElement;
    expect(within(sessionHeader).getAllByRole('button')).toHaveLength(4);
    expect(within(titlebar).queryByRole('button', { name: '打开 Session 文件' })).not.toBeInTheDocument();
    expect(within(titlebar).queryByRole('button', { name: '打开子 Agent 工作台' })).not.toBeInTheDocument();
    expect(within(titlebar).queryByRole('button', { name: '打开 Session 任务中心' })).not.toBeInTheDocument();
    expect(window.querySelector('.paw-session-workspace__side')).toBeNull();
    expect(window.querySelector('.agent-conversation-nav')).toBeNull();
  });

  it('opens the conversation with truthful workspace and permission context chips', async () => {
    const { container } = render(
      <ControlTransportProvider transport={createPreviewTransport()}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={liveSession()}
            recordId="session-live"
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );

    await screen.findByRole('textbox', { name: '消息' });
    const lead = await screen.findByRole('note', { name: 'Session 上下文' });
    expect(lead).toHaveTextContent('personal-agent-workbench · 工作区');
    expect(lead).toHaveTextContent('权限 · 按风险确认');
    // fx keeps message side as identity: no repeated "Agent/状态" caption row.
    expect(container.querySelector('.agent-assistant-turn__body > header')).toBeNull();
  });

  it('keeps one real composer mounted while switching between conversation and trace', async () => {
    const transport = createPreviewTransport();
    const user = userEvent.setup();
    const { container } = render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={liveSession()}
            recordId="session-live"
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );

    const composer = await screen.findByRole('textbox', { name: '消息' });
    expect(composer).toBeVisible();
    const conversation = container.querySelector('.paw-session-workspace__conversation');
    const trace = container.querySelector('.paw-session-workspace__trace');
    expect(conversation).not.toHaveAttribute('inert');
    expect(trace).toHaveAttribute('inert');
    expect(screen.queryByRole('complementary', { name: 'Session 工具侧栏' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Agent 轨迹' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Agent 轨迹' })).toHaveAttribute('aria-pressed', 'true'));
    expect(conversation).toHaveAttribute('inert');
    expect(trace).not.toHaveAttribute('inert');
    expect(screen.getByRole('textbox', { name: '消息' })).toBe(composer);
  });

  it('opens the 星空 view with the Session planet and its real subagent moons', async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <ControlTransportProvider transport={createPreviewTransport()}>
          <TooltipProvider>
            <PawSessionWorkspace
              record={liveSession()}
              recordId="session-live"
              onNewWork={vi.fn()}
              onSessionCreated={vi.fn()}
              onSessionUpdated={vi.fn()}
            />
          </TooltipProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await screen.findByRole('textbox', { name: '消息' });
    // Not watched → not mounted: the sky never polls behind the conversation.
    expect(screen.queryByRole('region', { name: 'Session 星空' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '星空' }));
    const sky = await screen.findByRole('region', { name: 'Session 星空' });
    await within(sky).findByRole('button', { name: /研究员 卫星/ });
    expect(within(sky).getByRole('button', { name: /审阅者 卫星/ })).toBeInTheDocument();
    expect(container.querySelector('.paw-session-workspace__conversation')).toHaveAttribute('inert');
    expect(container.querySelector('.paw-session-workspace__starfield')).not.toHaveAttribute('inert');

    await user.click(screen.getByRole('button', { name: '对话' }));
    expect(screen.queryByRole('region', { name: 'Session 星空' })).not.toBeInTheDocument();
    expect(container.querySelector('.paw-session-workspace__conversation')).not.toHaveAttribute('inert');
  });

  it('opens every secondary tool from one menu into one mutually exclusive sidebar', async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ControlTransportProvider transport={createPreviewTransport()}>
          <TooltipProvider>
            <PawSessionWorkspace
              record={liveSession()}
              recordId="session-live"
              onNewWork={vi.fn()}
              onSessionCreated={vi.fn()}
              onSessionUpdated={vi.fn()}
            />
          </TooltipProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await screen.findByRole('textbox', { name: '消息' });
    expect(screen.queryByRole('complementary', { name: 'Session 工具侧栏' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Session 工具' }));
    const menu = screen.getByRole('menu', { name: 'Session 工具菜单' });
    expect(within(menu).getAllByRole('menuitem')).toHaveLength(3);
    await user.click(within(menu).getByRole('menuitem', { name: '文件' }));

    let sidebar = screen.getByRole('complementary', { name: 'Session 工具侧栏' });
    expect(sidebar.querySelectorAll(':scope > .agent-files-panel, :scope > .session-subagent-panel, :scope > .agent-status-panel')).toHaveLength(1);
    expect(sidebar.querySelector('.agent-files-panel')).not.toBeNull();

    await user.click(screen.getByRole('button', { name: 'Session 工具' }));
    await user.click(screen.getByRole('menuitem', { name: '任务与状态' }));
    sidebar = screen.getByRole('complementary', { name: 'Session 工具侧栏' });
    expect(sidebar.querySelectorAll(':scope > .agent-files-panel, :scope > .session-subagent-panel, :scope > .agent-status-panel')).toHaveLength(1);
    expect(sidebar.querySelector('.agent-files-panel')).toBeNull();
    expect(sidebar.querySelector('.agent-status-panel')).not.toBeNull();
  });

  it('uses roving keyboard focus for the Session tools menu and restores the trigger on Escape', async () => {
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={createPreviewTransport()}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={liveSession()}
            recordId="session-live"
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );

    await screen.findByRole('textbox', { name: '消息' });
    const trigger = screen.getByRole('button', { name: 'Session 工具' });
    await user.click(trigger);
    const menu = screen.getByRole('menu', { name: 'Session 工具菜单' });
    const items = within(menu).getAllByRole('menuitem');

    expect(items[0]).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(items[1]).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(items[2]).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(items[0]).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(items[2]).toHaveFocus();
    await user.keyboard('{Home}');
    expect(items[0]).toHaveFocus();
    await user.keyboard('{End}');
    expect(items[2]).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu', { name: 'Session 工具菜单' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('closes on outside interaction and lets Tab leave the menu without a focus trap', async () => {
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={createPreviewTransport()}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={liveSession()}
            recordId="session-live"
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );

    const composer = await screen.findByRole('textbox', { name: '消息' });
    const trigger = screen.getByRole('button', { name: 'Session 工具' });
    await user.click(trigger);
    expect(screen.getByRole('menu', { name: 'Session 工具菜单' })).toBeInTheDocument();
    await user.click(composer);
    expect(screen.queryByRole('menu', { name: 'Session 工具菜单' })).not.toBeInTheDocument();

    await user.click(trigger);
    const menu = screen.getByRole('menu', { name: 'Session 工具菜单' });
    const items = within(menu).getAllByRole('menuitem');
    await user.keyboard('{End}');
    expect(items[2]).toHaveFocus();
    await user.tab();
    expect(screen.queryByRole('menu', { name: 'Session 工具菜单' })).not.toBeInTheDocument();
  });

  it('closes the floating tool rail with Escape and returns focus to its trigger', async () => {
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={createPreviewTransport()}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={liveSession()}
            recordId="session-live"
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );

    await screen.findByRole('textbox', { name: '消息' });
    await user.click(screen.getByRole('button', { name: 'Session 工具' }));
    await user.click(screen.getByRole('menuitem', { name: '文件' }));

    const sidebar = screen.getByRole('complementary', { name: 'Session 工具侧栏' });
    fireEvent.keyDown(sidebar, { key: 'Escape' });

    expect(screen.queryByRole('complementary', { name: 'Session 工具侧栏' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Session 工具' })).toHaveFocus();
  });

  it('projects the tool rail as a floating overlay so the message flow keeps the full viewport column', () => {
    // 浮层合同：桌面下侧栏绝对定位悬浮在对话之上；任何工具面板开启时，
    // 对话列仍然是唯一的网格列，绝不被挤出首屏。
    expect(agentMigratedCss).toMatch(
      /\.paw-desktop-root \.paw-session-workspace__side\s*\{[^}]*position:\s*absolute;/s,
    );
    expect(agentMigratedCss).toMatch(
      /\.paw-desktop-root \.paw-session-workspace\[data-panel='status'\] \.paw-session-workspace__body,\s*\.paw-desktop-root \.paw-session-workspace\[data-panel='subagents'\] \.paw-session-workspace__body,\s*\.paw-desktop-root \.paw-session-workspace\[data-panel='files'\] \.paw-session-workspace__body\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);/s,
    );
  });

  it('dresses the portaled Session chrome in the OS window palette, not a private one', () => {
    // header 被 portal 进 .paw-window-titlebar 后就离开了 .paw-session-workspace
    // 的作用域，--paw-chat-* 取不到；它此前退回 v1 基线的暖褐色，在冷灰蓝的
    // 标题栏里显出第二种黑。--paw-chrome-* 定义在 .paw-desktop-root 上，portal
    // 之后仍然解析得到，是这条 chrome 唯一该说的色板。
    const chrome = agentMigratedCss.slice(
      agentMigratedCss.indexOf('.paw-desktop-root .paw-session-workspace__view-switch {'),
      agentMigratedCss.indexOf('.paw-desktop-root .paw-session-workspace__attention'),
    );
    expect(chrome).not.toBe('');
    expect(chrome).toContain('var(--paw-chrome-ink)');
    expect(chrome).toContain('var(--paw-chrome-muted)');
    for (const warm of ['rgb(42 28 0', '#7d7a75', '#2c2c2b', 'rgb(36 31 27']) {
      expect(chrome, warm).not.toContain(warm);
    }
  });

  it('uses one compact recoverable line when the Session has no files', async () => {
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={createPreviewTransport()}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={{ ...liveSession(), workspaceRoots: [] }}
            recordId="session-empty-files"
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );

    await screen.findByRole('textbox', { name: '消息' });
    await user.click(screen.getByRole('button', { name: 'Session 工具' }));
    await user.click(screen.getByRole('menuitem', { name: '文件' }));

    const sidebar = screen.getByRole('complementary', { name: 'Session 工具侧栏' });
    const empty = within(sidebar).getByRole('status');
    expect(empty).toHaveTextContent('当前没有文件；选择工作区目录后即可浏览。');
    expect(within(empty).getByRole('button', { name: '选择目录' })).toBeInTheDocument();
    expect(within(sidebar).queryByText('还没有工作区目录')).not.toBeInTheDocument();
  });

  it('coalesces a live streaming burst into bounded store commits without reordering events', async () => {
    const sessionId = 'session-stream';
    const transport = new StubControlTransport('mock', {
      'agent.session.snapshot': {
        messages: [{
          schemaVersion: 'rag-ime.agent-message.v1',
          id: 'user-stream',
          sessionId,
          turnId: 'turn-stream',
          role: 'user',
          status: 'completed',
          blocks: [{
            id: 'user-stream:text',
            type: 'text',
            status: 'completed',
            presentationKind: 'markdown',
            data: { text: '请流式生成一段较长的回答' },
          }],
          attachments: [],
          citations: [],
          createdAtMs: 1,
          completedAtMs: 1,
        }],
        liveEvents: [],
        lastSequence: 0,
        resumeToken: '',
        status: 'busy',
      },
      'agent.session.models': {},
      'agent.session.commands': {},
      'agent.tools.list': {},
      'agent.runtime.get': {},
    });
    useAgentLiveStore.getState().clear(sessionId);
    render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={{ ...liveSession(), id: sessionId }}
            recordId={sessionId}
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );
    await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(transport.subscriptionCount('agent.session.events')).toBe(1));

    const streamedText = (projection: AgentProjectionState | undefined): string => {
      const block = projection?.messagesById['turn-stream:assistant']?.blocks
        .find((candidate) => candidate.id === 'turn-stream:assistant:text');
      return typeof block?.data.text === 'string' ? block.data.text : '';
    };
    const commits: Array<{ text: string; hasTool: boolean }> = [];
    const unsubscribe = useAgentLiveStore.subscribe((state, previous) => {
      const current = state.projections[sessionId];
      if (current === previous.projections[sessionId]) return;
      commits.push({
        text: streamedText(current),
        hasTool: Object.keys(current?.activitiesById ?? {}).length > 0,
      });
    });

    const leadingDeltas = Array.from({ length: 20 }, (_, index) => `前段${index};`);
    const trailingDeltas = Array.from({ length: 20 }, (_, index) => `后段${index};`);
    act(() => {
      let sequence = 0;
      const emit = (eventType: string, payload: Record<string, unknown>) => {
        sequence += 1;
        transport.emit('agent.session.events', parseAgentEvent({
          schemaVersion: 'rag-ime.agent-event.v1',
          eventId: `${sessionId}:${sequence}`,
          sessionId,
          turnId: 'turn-stream',
          sequence,
          createdAtMs: sequence * 5,
          eventType,
          payload: {
            messageId: 'turn-stream:assistant',
            blockId: 'turn-stream:assistant:text',
            ...payload,
          },
          resumeToken: `${sessionId}:${sequence}`,
        }));
      };
      for (const delta of leadingDeltas) emit('text_delta', { delta });
      emit('tool_started', { toolCallId: 'call-stream-tool', toolName: 'overview' });
      for (const delta of trailingDeltas) emit('text_delta', { delta });
      emit('turn_completed', { status: 'completed' });
    });
    unsubscribe();

    // 42 Runtime events reach the store as exactly 4 commits: the tool event
    // flushes the 20 leading deltas before its own commit, and the terminal
    // event flushes the 20 trailing deltas the same way. Per-token React
    // render and layout passes are gone; the visible order never changes.
    expect(commits).toHaveLength(4);
    const toolCommit = commits.find((commit) => commit.hasTool);
    expect(toolCommit?.text).toBe(leadingDeltas.join(''));
    expect(streamedText(useAgentLiveStore.getState().projections[sessionId]))
      .toBe([...leadingDeltas, ...trailingDeltas].join(''));
    expect(useAgentLiveStore.getState().projections[sessionId]?.turnsById['turn-stream']?.status)
      .toBe('completed');
    useAgentLiveStore.getState().clear(sessionId);
  });

  it('holds a follow-up beside the composer and gives it back when the turn is stopped', async () => {
    const sessionId = 'session-queue';
    const transport = busySessionTransport(sessionId);
    useAgentLiveStore.getState().clear(sessionId);
    render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={{ ...liveSession(), id: sessionId }}
            recordId={sessionId}
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(transport.subscriptionCount('agent.session.events')).toBe(1));
    act(() => { emitStreamDelta(transport, sessionId); });

    const user = userEvent.setup();
    // 干预/接续 reach Runtime now; 排队 is the composer's own hold.
    await user.click(await screen.findByRole('radio', { name: '排队' }));
    await user.type(composer, '等这轮结束再看依赖图');
    await user.click(screen.getByRole('button', { name: '排队，当前回合结束后发送' }));

    expect(await screen.findByText('1 条排队中')).toBeInTheDocument();
    expect(composer).toHaveValue('');
    // Nothing was handed to Runtime: the hold is entirely reversible.
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.prompt')).toEqual([]);
    expect(screen.getByRole('radio', { name: '排队 1' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '停止本轮' }));
    await waitFor(() => expect(screen.getByRole('textbox', { name: '消息' })).toHaveValue('等这轮结束再看依赖图'));
    expect(screen.queryByText('1 条排队中')).not.toBeInTheDocument();
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.prompt')).toEqual([]);
    useAgentLiveStore.getState().clear(sessionId);
  });

  it('sends exactly one held follow-up once the running turn settles', async () => {
    const sessionId = 'session-queue-drain';
    const transport = busySessionTransport(sessionId);
    useAgentLiveStore.getState().clear(sessionId);
    render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={{ ...liveSession(), id: sessionId }}
            recordId={sessionId}
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(transport.subscriptionCount('agent.session.events')).toBe(1));
    act(() => { emitStreamDelta(transport, sessionId); });

    const user = userEvent.setup();
    await user.click(await screen.findByRole('radio', { name: '排队' }));
    for (const text of ['第一条排队', '第二条排队']) {
      await user.type(composer, text);
      await user.click(screen.getByRole('button', { name: '排队，当前回合结束后发送' }));
    }
    expect(await screen.findByText('2 条排队中')).toBeInTheDocument();

    act(() => { emitTurnCompleted(transport, sessionId); });

    // Exactly one draft drains per settled turn, in the order it was held.
    await waitFor(() => expect(
      transport.requests.filter((request) => request.pathId === 'agent.session.prompt'),
    ).toHaveLength(1));
    expect(transport.requests.find((request) => request.pathId === 'agent.session.prompt')?.body)
      .toMatchObject({ message: '第一条排队' });
    await waitFor(() => expect(screen.getByText(/1 条排队中/)).toBeInTheDocument());
    useAgentLiveStore.getState().clear(sessionId);
  });

  it('lands the optimistic message and clears the draft at the click, before admission settles', async () => {
    const sessionId = 'session-instant-click';
    // The admission receipt never resolves inside this test: everything
    // asserted here must have happened synchronously with the click.
    const transport = new StubControlTransport('mock', {
      ...idleSessionRoutes(),
      'agent.session.prompt': () => new Promise(() => undefined),
    });
    useAgentLiveStore.getState().clear(sessionId);
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={{ ...liveSession(), id: sessionId }}
            recordId={sessionId}
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );

    const composer = await screen.findByRole('textbox', { name: '消息' });
    await user.type(composer, '请开始这轮实现');
    await user.click(screen.getByRole('button', { name: '发送' }));

    const projection = useAgentLiveStore.getState().projections[sessionId];
    const optimisticIds = Object.values(projection?.optimisticByClientMessageId ?? {});
    expect(optimisticIds).toHaveLength(1);
    expect(projection?.messagesById[optimisticIds[0]!]?.blocks[0]?.data.text).toBe('请开始这轮实现');
    expect(screen.getByRole('textbox', { name: '消息' })).toHaveValue('');
    useAgentLiveStore.getState().clear(sessionId);
  });

  it('unlocks the composer once admission settles, without waiting for the quiet snapshot', async () => {
    const sessionId = 'session-instant-unlock';
    let snapshotCalls = 0;
    // The quiet post-send snapshot never resolves in this test; if sending
    // still gated on it (the old behavior), the composer would spin forever
    // and the unlock assertion below would time out.
    const transport = new StubControlTransport('mock', {
      ...idleSessionRoutes(),
      'agent.session.snapshot': () => {
        snapshotCalls += 1;
        return snapshotCalls === 1
          ? { messages: [], liveEvents: [], lastSequence: 0, resumeToken: '', status: 'active' }
          : new Promise(() => undefined);
      },
      'agent.session.prompt': { ok: true },
    });
    useAgentLiveStore.getState().clear(sessionId);
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={{ ...liveSession(), id: sessionId }}
            recordId={sessionId}
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );

    const composer = await screen.findByRole('textbox', { name: '消息' });
    await user.type(composer, '请开始这轮实现');
    await user.click(screen.getByRole('button', { name: '发送' }));

    // The optimistic turn keeps the Session busy, so the delivery radios are
    // the visible proof of the send lock: they are disabled exactly while
    // `sending` is true. They must re-enable on the admission receipt alone.
    await waitFor(() => expect(screen.getByRole('radio', { name: '干预' })).toBeEnabled());
    const projection = useAgentLiveStore.getState().projections[sessionId];
    const optimisticIds = Object.values(projection?.optimisticByClientMessageId ?? {});
    expect(optimisticIds).toHaveLength(1);
    // Admission succeeded: the optimistic message stays queued, never failed.
    expect(projection?.messagesById[optimisticIds[0]!]?.status).toBe('queued');
    // The background refresh was launched but is still unresolved: the unlock
    // above therefore cannot have waited for it.
    expect(snapshotCalls).toBe(2);
    useAgentLiveStore.getState().clear(sessionId);
  });

  it('gives a failed prompt exactly one failure surface with its own recovery', async () => {
    const sessionId = 'session-prompt-failure';
    const transport = idleSessionTransport();
    useAgentLiveStore.getState().clear(sessionId);
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>
          <PawSessionWorkspace
            record={{ ...liveSession(), id: sessionId }}
            recordId={sessionId}
            onNewWork={vi.fn()}
            onSessionCreated={vi.fn()}
            onSessionUpdated={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>,
    );

    const composer = await screen.findByRole('textbox', { name: '消息' });
    await user.type(composer, '请开始这轮实现');
    await user.click(screen.getByRole('button', { name: '发送' }));

    // FailOptimistic owns the turn. This file does not mock Virtuoso geometry,
    // so the turn card itself is covered in agent-feature tests; here we lock
    // the PAWOS-specific bug: no second 重新同步 banner for the same failure.
    await waitFor(() => {
      const projection = useAgentLiveStore.getState().projections[sessionId];
      expect(projection?.turnOrder.some((turnId) => (
        projection.turnsById[turnId]?.status === 'failed'
      ))).toBe(true);
    });
    expect(transport.requests.some((request) => request.pathId === 'agent.session.prompt')).toBe(true);
    expect(document.querySelector('.paw-session-workspace__error')).toBeNull();
    expect(screen.queryByRole('button', { name: '重新同步' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '消息' })).toHaveValue('请开始这轮实现');
    useAgentLiveStore.getState().clear(sessionId);
  });

  it('uses one compact on-demand row when the Session has no subagents', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const transport = new StubControlTransport('mock', {
      'agent.subagents.list': { ok: true, items: [] },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ControlTransportProvider transport={transport}>
          <TooltipProvider>
            <SessionSubagentPanel
              compactEmpty
              open
              session={liveSession()}
              sessionId="session-no-subagents"
              tools={[]}
              onClose={vi.fn()}
            />
          </TooltipProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('当前没有子 Agent；需要时可在这里启动。')).toBeVisible();
    expect(screen.queryByRole('region', { name: '子 Agent 运行图' })).not.toBeInTheDocument();
  });

});

/** A Session whose snapshot opens on one running turn, so the composer offers
 *  the busy delivery choices a queued follow-up competes with. */
function busySessionTransport(sessionId: string): StubControlTransport {
  return new StubControlTransport('mock', {
    'agent.session.snapshot': {
      messages: [{
        schemaVersion: 'rag-ime.agent-message.v1',
        id: `${sessionId}:user`,
        sessionId,
        turnId: 'turn-busy',
        role: 'user',
        status: 'completed',
        blocks: [{
          id: `${sessionId}:user:text`,
          type: 'text',
          status: 'completed',
          presentationKind: 'markdown',
          data: { text: '请开始这轮实现' },
        }],
        attachments: [],
        citations: [],
        createdAtMs: 1,
        completedAtMs: 1,
      }],
      liveEvents: [],
      lastSequence: 0,
      resumeToken: '',
      status: 'busy',
    },
    'agent.session.models': {},
    'agent.session.commands': {},
    'agent.tools.list': {},
    'agent.runtime.get': {},
    'agent.session.prompt': { ok: true },
    'agent.session.abort': { ok: true },
  });
}

/** Route table for an idle Session with no prompt behavior chosen yet. */
function idleSessionRoutes(): ConstructorParameters<typeof StubControlTransport>[1] {
  return {
    'agent.session.snapshot': {
      messages: [],
      liveEvents: [],
      lastSequence: 0,
      resumeToken: '',
      status: 'active',
    },
    'agent.session.models': {},
    'agent.session.commands': {},
    'agent.tools.list': {},
    'agent.runtime.get': {},
  };
}

/** An idle Session whose Runtime rejects the prompt, so submitting produces one
 *  real failed turn instead of a stub acknowledgement. */
function idleSessionTransport(): StubControlTransport {
  return new StubControlTransport('mock', {
    ...idleSessionRoutes(),
    'agent.session.prompt': () => {
      throw new Error('provider_request_failed');
    },
  });
}

function emitStreamDelta(transport: StubControlTransport, sessionId: string): void {
  transport.emit('agent.session.events', parseAgentEvent({
    schemaVersion: 'rag-ime.agent-event.v1',
    eventId: `${sessionId}:1`,
    sessionId,
    turnId: 'turn-busy',
    sequence: 1,
    createdAtMs: 5,
    eventType: 'text_delta',
    payload: {
      messageId: 'turn-busy:assistant',
      blockId: 'turn-busy:assistant:text',
      delta: '正在推进…',
    },
    resumeToken: `${sessionId}:1`,
  }));
}

function emitTurnCompleted(transport: StubControlTransport, sessionId: string): void {
  transport.emit('agent.session.events', parseAgentEvent({
    schemaVersion: 'rag-ime.agent-event.v1',
    eventId: `${sessionId}:2`,
    sessionId,
    turnId: 'turn-busy',
    sequence: 2,
    createdAtMs: 10,
    eventType: 'turn_completed',
    payload: { messageId: 'turn-busy:assistant', status: 'completed' },
    resumeToken: `${sessionId}:2`,
  }));
}

function liveSession(): SessionSummary {
  return {
    id: 'session-live',
    title: '完整迁移',
    mode: 'coordinator',
    status: 'active',
    roleId: 'builder',
    roleVersion: '1',
    roleBookRevisionId: '',
    updatedAtMs: 170,
    workspaceRoots: ['/Volumes/undo 4t/git/personal-agent-workbench'],
    executionMode: 'per_action',
    modelProfile: 'openai/gpt-5.6-sol',
  };
}
