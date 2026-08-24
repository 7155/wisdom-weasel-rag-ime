import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { TooltipProvider } from '@/components/primitives';
import { SessionSubagentPanel } from '@/features/agent/delegation/SessionSubagentPanel';
import type { SessionSummary } from '@/features/agent/types';
import { StubControlTransport } from '@/test/stub-control-transport';
import { PawWindowFrame } from '../shell/PawWindowLayer';
import { PawSessionWorkspace } from './PawSessionWorkspace';

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
    expect(within(titlebar).getByRole('button', { name: 'Session 工具' })).toBeInTheDocument();
    const sessionHeader = titlebar.querySelector('.paw-session-workspace__header') as HTMLElement;
    expect(within(sessionHeader).getAllByRole('button')).toHaveLength(3);
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
