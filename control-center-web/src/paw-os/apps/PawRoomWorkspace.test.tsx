import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { previewRoomSnapshot } from '@/app/preview-room-data';
import { TooltipProvider } from '@/components/primitives';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import type { RoomSummary } from '@/features/rooms/room-types';
import { PawWindowFrame } from '../shell/PawWindowLayer';
import { PawRoomWorkspace } from './PawRoomWorkspace';

afterEach(cleanup);

describe('PAWOS Room collaboration tools', () => {
  it('opens one purpose-built Sol collaboration view instead of four duplicate summaries', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    const { container, room } = renderRoom(900, openWindow);
    await screen.findByRole('textbox', { name: '协作消息' });

    const primaryNavigation = screen.getByRole('navigation', { name: 'Room 工作台视图' });
    expect(within(primaryNavigation).getAllByRole('button')).toHaveLength(3);
    expect(within(primaryNavigation).getByRole('button', { name: '公开对话' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(primaryNavigation).getByRole('button', { name: '协作态势' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(primaryNavigation).getByRole('button', { name: '星空' })).toHaveAttribute('aria-pressed', 'false');
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-panel', 'focus');

    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    expect(within(tools).getAllByRole('tab')).toHaveLength(2);
    expect(within(tools).getByRole('tab', { name: '态势' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('region', { name: 'Room 当前协作' })).toHaveTextContent('任务图依赖验证');
    expect(within(tools).getByRole('tree', { name: '任务树' })).toHaveTextContent('实现 Room 依赖数据投影');
    const timeline = screen.getByRole('log', { name: '公开对话时间线' });
    const userMessage = within(timeline).getByText('并行实现 Room 任务图与依赖数据，整合后交给独立伙伴复核。').closest('article');
    expect(userMessage).not.toBeNull();
    expect(within(userMessage!).queryByText('你')).not.toBeInTheDocument();
    const earthMessage = within(timeline).getByText('我已把实时进展收拢在同一条消息里；完成后会在原处留下清晰结果。').closest('article');
    expect(within(earthMessage!).getByText('Earth')).toBeInTheDocument();
    /* UR-054：进入 Room 只自动展开后台伙伴卫星窗，主 Room 保持焦点，
       不会有任何前台窗口调用。 */
    expect(openWindow.mock.calls.length).toBeGreaterThan(0);
    for (const [request] of openWindow.mock.calls) {
      expect(request).toMatchObject({ background: true, target: expect.objectContaining({ kind: 'participant' }) });
    }
    expect(new Set(openWindow.mock.calls.map(([request]) => request.target.id)).size).toBe(openWindow.mock.calls.length);

    /* PF-CM-013/PF-CM-020：态势弹出是真实可达的卫星入口，指向 focus 面板。 */
    await user.click(within(tools).getByRole('button', { name: '在卫星窗中打开协作态势' }));
    expect(openWindow).toHaveBeenLastCalledWith(expect.objectContaining({
      appId: 'agent',
      target: expect.objectContaining({ kind: 'room', id: room.id, panel: 'focus' }),
    }));

    await user.click(within(tools).getByRole('button', { name: '关闭协作态势' }));

    expect(screen.getByRole('main', { name: /主 Room/ })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Room 协作态势' })).not.toBeInTheDocument();
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-panel', 'none');
  });

  it('turns the whole Room into one clickable solar system in 星空 mode', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    const { container } = renderRoom(900, openWindow);
    await screen.findByRole('textbox', { name: '协作消息' });

    await user.click(screen.getByRole('button', { name: '星空' }));

    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-view', 'starfield');
    // The sky is an immersive fullscreen overlay portaled to <body>; it is
    // React.lazy, so the region resolves asynchronously after the click.
    const sky = await screen.findByRole('region', { name: 'Room 星空' });
    expect(sky).toHaveAttribute('data-immersive');
    expect(within(sky).getByText('Sol')).toBeInTheDocument();
    // The workspace behind the overlay keeps its state for the way back.
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeInTheDocument();

    // Picking a planet opens its detail card; opening the partner window is
    // an explicit second action, so a stray click never steals the stage.
    await user.click(within(sky).getByRole('button', { name: /^Mars，/ }));
    const card = within(sky).getByRole('complementary', { name: '天体详情' });
    await user.click(within(card).getByRole('button', { name: '打开伙伴窗口' }));

    const foregroundCalls = openWindow.mock.calls.filter(([request]) => request.background === false);
    expect(foregroundCalls).toHaveLength(1);
    expect(foregroundCalls[0]?.[0]).toMatchObject({
      target: expect.objectContaining({
        kind: 'participant',
        id: 'participant-firstlight',
        title: 'Mars',
      }),
    });

    // The exit control returns to the conversation view.
    await user.click(within(sky).getByRole('button', { name: /返回 Room/ }));
    expect(screen.queryByRole('region', { name: 'Room 星空' })).not.toBeInTheDocument();
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-view', 'conversation');
  });

  it('fronts a partner satellite only when the user explicitly clicks that planet', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    renderRoom(900, openWindow);
    await screen.findByRole('textbox', { name: '协作消息' });

    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    const partners = within(tools).getByRole('list', { name: '行星伙伴' });
    await user.click(within(partners).getByRole('button', { name: /Mars/ }));
    await user.click(within(tools).getByRole('button', { name: '打开 Mars 伙伴窗口' }));

    expect(screen.queryByRole('button', { name: /铺开 .* 位/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Room 协作态势' })).not.toBeInTheDocument();
    /* 自动展开只允许 background 调用；唯一的前台调用来自用户点击 Mars。 */
    const foregroundCalls = openWindow.mock.calls.filter(([request]) => request.background === false);
    expect(foregroundCalls).toHaveLength(1);
    expect(foregroundCalls[0]?.[0]).toMatchObject({
      target: expect.objectContaining({
        id: 'participant-firstlight',
        title: 'Mars',
        subtitle: expect.stringContaining('Agent 2'),
      }),
    });
  });
});

function renderRoom(width: number, openWindow = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const room = previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <ControlTransportProvider transport={createPreviewTransport()}>
          <PawOsDesktopProvider openWindow={openWindow}>
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
                title={`Room ${width}`}
                windowChrome="agent-room"
                windowId={`room-${width}`}
                zIndex={10}
              >
                <PawRoomWorkspace
                  personas={[]}
                  record={room}
                  recordId={room.id}
                  onRoomUpdated={vi.fn()}
                />
              </PawWindowFrame>
            </TooltipProvider>
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    ),
    room,
  };
}
