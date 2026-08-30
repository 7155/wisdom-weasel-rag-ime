import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { GlobalFeedbackProvider } from '@/components/feedback';
import { MockControlTransport } from '@/test/mock-transport';
import { PawDesktopProvider, usePawDesktopStore } from '../runtime/desktop-context';
import { PawBackgroundActivity } from './PawBackgroundActivity';
import { PawNotificationCenter } from './PawNotificationCenter';
import { pawMemoryMaintenanceActivity, PawWorkDirectoryProvider, usePawWorkDirectory } from './PawWorkDirectory';
import statusCss from './paw-shell-status.css?raw';

afterEach(() => cleanup());

describe('PawBackgroundActivity', () => {
  it('renders its portal above the fixed PAWOS desktop stacking context', () => {
    expect(statusCss).toMatch(/\.ui-popover\.paw-background-activity__popover\s*\{[\s\S]*?z-index:\s*1200/);
  });

  it('recognizes the real maintenance projection without inventing a conversation Session', () => {
    expect(pawMemoryMaintenanceActivity({
      job: {
        jobId: 'memory-maintenance:active',
        state: 'running',
        progress: { summary: '正在整理 4 个来源' },
        updatedAtMs: 42,
      },
    })).toEqual({
      id: 'memory-maintenance:active',
      title: '自动记忆整理',
      detail: '正在整理 4 个来源',
      updatedAtMs: 42,
    });
    expect(pawMemoryMaintenanceActivity({ projection: { running: true, lastRunAtMs: 42 } })).toBeNull();
    expect(pawMemoryMaintenanceActivity({ projection: { running: false } })).toBeNull();
  });

  it('lists only real running conversations and returns directly to their canonical windows', async () => {
    renderActivity(new MockControlTransport({ routes: {
      'agent.sessions.list': { ok: true, items: [
        session('memory-maintenance', '自动记忆整理', 'busy'),
        session('conversation', '整理 PAWOS 桌面', 'busy'),
        session('room-partner', '桌面协作 · Agent 1', 'busy', 'room-running'),
        session('idle', '已经空闲', 'idle'),
      ] },
      'agent.rooms.list': { ok: true, items: [{
        id: 'room-running',
        title: '桌面协作',
        status: 'active',
        updatedAtMs: 30,
        workspaceRoots: ['/work/paw'],
        participants: [],
        workItems: [],
      }] },
    } }));

    const trigger = await screen.findByRole('button', { name: '3 个后台工作正在运行' });
    fireEvent.click(trigger);

    const panel = await screen.findByRole('region', { name: '后台运行' });
    expect(within(panel).queryByText('自动记忆整理', { selector: 'small' })).not.toBeInTheDocument();
    expect(within(panel).getAllByText('对话 Agent')).toHaveLength(2);
    expect(within(panel).getByText('Room 协作')).toBeInTheDocument();
    expect(within(panel).queryByText('已经空闲')).not.toBeInTheDocument();

    fireEvent.click(within(panel).getByRole('button', { name: /整理 PAWOS 桌面/ }));
    await waitFor(() => expect(screen.getByTestId('open-window-ids')).toHaveTextContent('agent:conversation'));
  });

  it('stays absent when the Runtime reports no running work', async () => {
    renderActivity(new MockControlTransport({ routes: {
      'agent.sessions.list': { ok: true, items: [session('idle', '已经空闲', 'idle')] },
      'agent.rooms.list': { ok: true, items: [] },
    } }));

    await waitFor(() => expect(screen.queryByRole('button', { name: /后台工作正在运行/ })).not.toBeInTheDocument());
  });

  it('publishes a real notification when a canonical running Session exits busy state', async () => {
    let status = 'busy';
    renderActivity(new MockControlTransport({ routes: {
      'agent.sessions.list': () => ({ ok: true, items: [session('conversation', '整理 PAWOS 桌面', status)] }),
      'agent.rooms.list': { ok: true, items: [] },
    } }));
    await screen.findByRole('button', { name: '1 个后台工作正在运行' });

    status = 'idle';
    fireEvent.click(screen.getByRole('button', { name: '刷新后台目录' }));
    const notificationTrigger = await screen.findByRole('button', { name: '通知中心，1 条通知' });
    fireEvent.click(notificationTrigger);
    expect(await screen.findByText('整理 PAWOS 桌面 已结束运行')).toBeInTheDocument();
  });

  it('warns when a running Room participant faults instead of reporting a normal finish', async () => {
    let status = 'busy';
    renderActivity(new MockControlTransport({ routes: {
      'agent.sessions.list': () => ({ ok: true, items: [session('room-partner', '桌面协作 · Agent 1', status, 'room-running')] }),
      'agent.rooms.list': { ok: true, items: [{
        id: 'room-running',
        title: '桌面协作',
        status: 'active',
        updatedAtMs: 30,
        workspaceRoots: ['/work/paw'],
        participants: [],
        workItems: [],
      }] },
    } }));
    await screen.findByRole('button', { name: '1 个后台工作正在运行' });

    status = 'faulted';
    fireEvent.click(screen.getByRole('button', { name: '刷新后台目录' }));
    const notificationTrigger = await screen.findByRole('button', { name: '通知中心，1 条通知' });
    fireEvent.click(notificationTrigger);
    expect(await screen.findByText('桌面协作 需要处理')).toBeInTheDocument();
  });

  it('warns when the real Memory maintenance job fails', async () => {
    let state = 'running';
    renderActivity(new MockControlTransport({ routes: {
      'agent.sessions.list': { ok: true, items: [] },
      'agent.rooms.list': { ok: true, items: [] },
      'agent.memoryMaintenance.run': () => ({
        ok: state !== 'failed',
        job: {
          jobId: 'memory-maintenance:active',
          state,
          error: state === 'failed' ? 'provider down' : '',
          updatedAtMs: 42,
        },
      }),
    } }));
    await screen.findByRole('button', { name: '1 个后台工作正在运行' });

    state = 'failed';
    fireEvent.click(screen.getByRole('button', { name: '刷新后台目录' }));
    const notificationTrigger = await screen.findByRole('button', { name: '通知中心，1 条通知' });
    fireEvent.click(notificationTrigger);
    expect(await screen.findByText('自动记忆整理 需要处理')).toBeInTheDocument();
    expect(screen.getByText(/provider down/)).toBeInTheDocument();
  });
});

function renderActivity(transport: MockControlTransport) {
  return render(
    <GlobalFeedbackProvider>
      <ControlTransportProvider transport={transport}>
        <PawDesktopProvider>
          <PawWorkDirectoryProvider maintenancePollIntervalMs={60_000} pollIntervalMs={60_000}>
            <PawBackgroundActivity />
            <PawNotificationCenter />
            <RefreshProbe />
            <WindowProbe />
          </PawWorkDirectoryProvider>
        </PawDesktopProvider>
      </ControlTransportProvider>
    </GlobalFeedbackProvider>,
  );
}

function RefreshProbe() {
  const { refresh } = usePawWorkDirectory();
  return <button onClick={() => void refresh()} type="button">刷新后台目录</button>;
}

function WindowProbe() {
  const ids = usePawDesktopStore((state) => Object.keys(state.windows).sort().join(','));
  return <output data-testid="open-window-ids">{ids}</output>;
}

function session(id: string, title: string, status: string, roomId?: string) {
  return {
    id,
    title,
    mode: 'assistant',
    status,
    roleId: 'default',
    roleVersion: '1',
    roleBookRevisionId: 'r1',
    updatedAtMs: 20,
    workspaceRoots: ['/work/paw'],
    ...(roomId ? { roomParticipant: { roomId } } : {}),
  };
}
